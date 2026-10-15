"""Saved routing plans, explicit preflight and verified LWRP destination changes."""
from localization import tr
import ipaddress
import json
import socket
import time
import uuid
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QComboBox, QTreeWidget, QTreeWidgetItem, QInputDialog, QMessageBox, QLabel, QPlainTextEdit)
from routing import read_destinations, stream_key
from audio_monitor import AudioReceiver


def channel_address(channel):
    channel = int(channel)
    if not 1 <= channel <= 65535:
        raise ValueError('Channel must be between 1 and 65535')
    return f'239.192.{channel >> 8}.{channel & 255}'


def validate_plan(plan):
    if not isinstance(plan.get('name'), str) or not plan['name'].strip() or len(plan['name']) > 120:
        raise ValueError('Enter a scenario name (up to 120 characters)')
    if not 1 <= len(plan.get('steps', [])) <= 32:
        raise ValueError('A scenario needs 1–32 destination assignments')
    seen = set()
    for step in plan['steps']:
        address = str(ipaddress.IPv4Address(step['ip']))
        if address != step['ip'] or not 1 <= int(step['output']) <= 4096:
            raise ValueError('Invalid receiver or output')
        key = address, int(step['output'])
        if key in seen:
            raise ValueError('Each destination may appear only once')
        seen.add(key)
        for mode in ('primary', 'backup'):
            channel_address(step[mode])
    return plan


class ScenarioStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def plans(self):
        return [validate_plan(json.loads(p.read_text(encoding='utf-8'))) for p in sorted(self.folder.glob('*.json'))]

    def save(self, plan):
        validate_plan(plan)
        key = str(uuid.UUID(plan['id'])) if plan.get('id') else str(uuid.uuid4())
        result = dict(plan, id=key)
        path = self.folder / (key + '.json')
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        return result


def preflight(plan, mode, reader=read_destinations):
    validate_plan(plan)
    if mode not in ('primary', 'backup'):
        raise ValueError('Invalid scenario mode')
    result, observations = [], {}
    for step in plan['steps']:
        if step['ip'] not in observations:
            observations[step['ip']] = reader(step['ip'])
        observation = observations[step['ip']]
        if not observation['complete']:
            raise ValueError('Partial destination response: ' + step['ip'])
        destination = next((d for d in observation['destinations'] if d['slot'] == int(step['output'])), None)
        if destination is None:
            raise ValueError('Destination not reported by device: ' + step['ip'])
        result.append(dict(ip=step['ip'], output=int(step['output']), before=destination['address'],
                           after=channel_address(step[mode]), model=observation['version']['DEVN']))
    return result


def apply_assignment(step, password='', port=93, reader=None):
    reader = reader or (lambda ip: read_destinations(ip, port=port))
    ip = str(ipaddress.IPv4Address(step['ip']))
    output = int(step['output'])
    address = str(ipaddress.IPv4Address(step['after']))
    if not address.startswith('239.192.') or not 1 <= output <= 4096:
        raise ValueError('Only validated Livewire destination assignments are supported')
    if any(ord(c) < 32 or ord(c) > 126 or c in '"\\' for c in password):
        raise ValueError('This LWRP adapter cannot safely encode the supplied password')
    before = reader(ip)
    current = next((d for d in before['destinations'] if d['slot'] == output), None)
    if not before['complete'] or not current or before['version']['DEVN'] != step['model'] or current['address'] != step['before']:
        raise ValueError('Destination changed since preflight; nothing written to this destination')
    if stream_key(current['address']) == stream_key(address):
        return 'Already assigned'
    with socket.create_connection((ip, port), timeout=2) as connection:
        connection.settimeout(.2)
        # Never put passwords or wire commands in events or run reports.
        if password:
            connection.sendall(('LOGIN "' + password + '"\r\n').encode('ascii'))
        connection.sendall(f'DST {output} ADDR:"{address}"\r\n'.encode('ascii'))
        deadline = time.monotonic() + .5
        response = bytearray()
        while time.monotonic() < deadline:
            try:
                data = connection.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            response.extend(data)
            if b'ERROR' in response:
                raise ValueError('Device rejected authentication or assignment; inspect actual routing')
            if len(response) > 65536:
                raise ValueError('Unexpectedly large device indication')
    after = reader(ip)
    actual = next((d for d in after['destinations'] if d['slot'] == output), None)
    if not after['complete'] or not actual or stream_key(actual['address']) != stream_key(address):
        raise ValueError('Assignment not verified. Actual state may have changed; refresh destinations')
    return 'Verified'


class ScenarioJob(QThread):
    completed = Signal(object)
    failed = Signal(str)
    def __init__(self, plan=None, mode=None, steps=None, credentials=None, sources=None, interface_index=None, parent=None):
        super().__init__(parent)
        self.plan, self.mode, self.steps = plan, mode, steps
        self.credentials = credentials or {}
        self.sources, self.interface_index = sources or [], interface_index

    def run(self):
        try:
            if self.steps is None:
                for source in self.sources:
                    if self.isInterruptionRequested():
                        raise ValueError('Source verification cancelled')
                    receiver = AudioReceiver(source, self.interface_index)
                    receiver.start()
                    try:
                        deadline = time.monotonic() + 1.5
                        while time.monotonic() < deadline and not self.isInterruptionRequested():
                            time.sleep(.05)
                        with receiver.buffer.lock:
                            b = receiver.buffer
                            if b.error or b.packets < 10 or time.monotonic() - b.last_packet > .5:
                                raise ValueError('No verified compatible stream for channel ' + str(source['channel']))
                            if b.gaps / max(1, b.packets + b.gaps) > .01:
                                raise ValueError('Source check exceeds 1% packet gaps: channel ' + str(source['channel']))
                    finally:
                        receiver.requestInterruption()
                        receiver.wait()
                self.completed.emit(preflight(self.plan, self.mode))
                return
            results = []
            for index, step in enumerate(self.steps):
                if self.isInterruptionRequested():
                    results.extend(dict(s, result='Not executed: cancelled') for s in self.steps[index:])
                    break
                try:
                    outcome = apply_assignment(step, self.credentials.get(step['ip'], ''))
                    results.append(dict(step, result=outcome))
                except (OSError, ValueError) as exc:
                    results.append(dict(step, result='Unverified: ' + str(exc)))
                    results.extend(dict(s, result='Not executed: earlier step failed') for s in self.steps[index + 1:])
                    break
            self.completed.emit(results)
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))
        finally:
            self.credentials.clear()


class ScenariosPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.store = ScenarioStore(atlas.data_dir / 'state' / 'scenarios')
        self.policy_path = atlas.data_dir / 'state' / 'operation-policy.json'
        self.job = None
        self.steps = []
        self.plan_id = None
        self.preview_steps = None
        self.draft_path = atlas.data_dir / 'state' / 'scenario-draft.json'
        self.restoring = True
        layout = QVBoxLayout(self)
        explanation = QLabel(tr('Scenarios · saved on this computer · routing changes require preflight and an authorized target'))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.saved = QComboBox()
        layout.addWidget(self.saved)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr('Scenario name'))
        layout.addWidget(self.name)
        row = QHBoxLayout()
        for title, callback in [('New', self.new), ('Load', self.load), ('Add Assignment', self.add_step),
                                ('Remove Assignment', self.remove_step), ('Save', self.save)]:
            button = QPushButton(tr(title))
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([tr('Receiver'), tr('Output'), tr('Primary channel'), tr('Backup channel')])
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        self.primary = QPushButton(tr('Check Primary'))
        self.backup = QPushButton(tr('Check Backup'))
        self.execute = QPushButton(tr('Execute Reviewed Assignments'))
        self.execute.setEnabled(False)
        self.primary.clicked.connect(lambda: self.check('primary'))
        self.backup.clicked.connect(lambda: self.check('backup'))
        self.execute.clicked.connect(self.run_reviewed)
        for b in (self.primary, self.backup, self.execute): row.addWidget(b)
        layout.addLayout(row)
        authorize = QPushButton(tr('Director: Authorize Test Target…'))
        authorize.clicked.connect(self.authorize_target)
        layout.addWidget(authorize)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        layout.addWidget(self.status)
        self.name.textChanged.connect(self.invalidate)
        self.reload()
        if self.draft_path.exists():
            try:
                draft = json.loads(self.draft_path.read_text(encoding='utf-8'))
                if not isinstance(draft.get('name'), str) or not isinstance(draft.get('steps'), list):
                    raise ValueError('Invalid scenario draft')
                for step in draft['steps']:
                    validate_plan(dict(name='Draft', steps=[step], id=draft.get('id')))
                self.steps, self.plan_id = draft['steps'], draft.get('id')
                self.name.setText(draft['name'])
                self.render()
                self.status.setPlainText(tr('Unsaved scenario draft restored. No device changes made.'))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.status.setPlainText(str(exc))
        self.restoring = False

    def store_draft(self):
        if self.restoring: return
        try:
            self.draft_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.draft_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.plan(), ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.draft_path)
        except OSError as exc:
            self.status.setPlainText(tr('Could not save scenario draft: ') + str(exc))

    def policy(self):
        return json.loads(self.policy_path.read_text()) if self.policy_path.exists() else {'allowed': [], 'protected': []}

    def authorize_target(self):
        if self.job: return
        try:
            self.atlas.access.require_director()
            address, ok = QInputDialog.getText(self, tr('Authorize Test Target'), tr('Exact IPv4 address of the test receiver:'))
            if not ok: return
            address = str(ipaddress.IPv4Address(address.strip()))
            policy = self.policy()
            if address in policy['protected']:
                raise ValueError('This target is protected by the local deployment policy')
            if QMessageBox.question(self, tr('Authorize Target'), tr('Allow scenario routing writes to {v0} from this workstation?\nUse a test receiver whose interruption cannot affect the on-air path.', v0=address)) != QMessageBox.Yes:
                return
            policy['allowed'] = sorted(set(policy['allowed']) | {address})
            temp = self.policy_path.with_suffix('.tmp')
            temp.write_text(json.dumps(policy, indent=2))
            temp.replace(self.policy_path)
            self.atlas.record('Scenario test target authorized', ip=address)
        except (OSError, ValueError, PermissionError) as exc:
            self.status.setPlainText(str(exc))

    def invalidate(self):
        self.preview_steps = None
        self.execute.setEnabled(False)
        self.store_draft()

    def reload(self):
        self.saved.clear()
        try:
            for p in self.store.plans(): self.saved.addItem(p['name'], p)
        except (OSError, ValueError, KeyError) as exc: self.status.setPlainText((tr('Could not load scenarios: ') + str(exc)))

    def render(self):
        self.tree.clear()
        for step in self.steps:
            self.tree.addTopLevelItem(QTreeWidgetItem([str(step[k]) for k in ('ip', 'output', 'primary', 'backup')]))
        self.invalidate()

    def new(self):
        if self.job: return
        self.steps, self.plan_id = [], None
        self.name.clear()
        self.render()

    def load(self):
        if self.job: return
        plan = self.saved.currentData()
        if plan:
            self.steps, self.plan_id = [dict(s) for s in plan['steps']], plan['id']
            self.name.setText(plan['name'])
            self.render()

    def add_step(self):
        if self.job: return
        address, ok = QInputDialog.getText(self, tr('Receiver'), tr('Receiver IPv4 address:'))
        if not ok: return
        try: address = str(ipaddress.IPv4Address(address.strip()))
        except ValueError:
            self.status.setPlainText(tr('Enter a valid receiver IPv4 address.')); return
        step = {'ip': address}
        for key, label, maximum in [('output', 'Receiver output number', 4096), ('primary', 'Primary Livewire channel', 65535), ('backup', 'Backup Livewire channel', 65535)]:
            value, ok = QInputDialog.getInt(self, tr('Assignment'), label, 1, 1, maximum)
            if not ok: return
            step[key] = value
        self.steps.append(step)
        self.render()

    def remove_step(self):
        if self.job: return
        index = self.tree.indexOfTopLevelItem(self.tree.currentItem())
        if index >= 0: self.steps.pop(index); self.render()

    def plan(self):
        return dict(id=self.plan_id, name=self.name.text().strip(), steps=[dict(s) for s in self.steps])

    def save(self):
        if self.job or not self.atlas.access.allowed('scenarios'): return
        try:
            plan = self.store.save(self.plan())
            self.plan_id = plan['id']
            self.store_draft()
            self.reload()
            if hasattr(self.atlas, 'scenarios_nav'): self.atlas.scenarios_nav.refresh()
            if hasattr(self.atlas, 'scenarios_home'): self.atlas.scenarios_home.refresh()
            self.status.setPlainText(tr('Scenario saved. No device changes made.'))
        except (OSError, ValueError) as exc: self.status.setPlainText(str(exc))

    def check(self, mode):
        if self.job or not all(self.atlas.access.allowed(p) for p in ('scenarios', 'network', 'audio')): return
        self.invalidate()
        try:
            plan = validate_plan(self.plan())
            policy = self.policy()
            for step in self.steps:
                if step['ip'] in policy['protected'] or step['ip'] not in policy['allowed']:
                    raise ValueError('Target is not authorized for scenario testing: ' + step['ip'])
            interface = self.atlas.interface_objects.get(self.atlas.interfaces.currentData())
            if not interface:
                raise ValueError('Select the broadcast network adapter for source verification')
            sources = []
            for channel in sorted({int(s[mode]) for s in plan['steps']}):
                matches = [s for s in self.atlas.audio_sources.sources.values() if s.get('channel') == channel and s.get('channels', 2) == 2]
                if len(matches) != 1:
                    raise ValueError('Channel must identify one enabled stereo source: ' + str(channel))
                sources.append(dict(matches[0]))
            self.start_job(ScenarioJob(plan=plan, mode=mode, sources=sources, interface_index=interface.index(), parent=self.atlas), self.checked)
        except (ValueError, OSError) as exc: self.status.setPlainText(str(exc))

    def start_job(self, job, callback):
        self.job = job
        self.atlas.jobs.append(job)
        job.completed.connect(callback)
        job.failed.connect(self.status.setPlainText)
        job.finished.connect(self.finished)
        self.execute.setEnabled(False)
        self.status.setPlainText(tr('Working…'))
        job.start()

    def finished(self):
        self.atlas.jobs.remove(self.job)
        self.job.deleteLater()
        self.job = None
        self.execute.setEnabled(bool(self.preview_steps) and self.atlas.access.allowed('scenarios'))

    def checked(self, steps):
        self.preview_steps = steps
        self.preview_at = time.monotonic()
        self.status.setPlainText(('\n'.join((f"{s['ip']} / output {s['output']}: {s['before']} → {s['after']}" for s in steps)) + tr('\n\nDevice assignments read. Compatible source packets verified over a 1.5-second window, with at most 1% gaps. This is not a guarantee of programme content.\nChanges are sequential, not atomic. Reboot persistence is not claimed.')))

    def run_reviewed(self):
        if self.job or not self.preview_steps or not all(self.atlas.access.allowed(p) for p in ('scenarios', 'device_ui', 'network')): return
        if time.monotonic() - self.preview_at > 30:
            self.invalidate(); self.status.setPlainText(tr('Preflight expired. Check the scenario again.')); return
        if QMessageBox.question(self, tr('Execute Scenario'), tr('Apply the displayed destination assignments?\nA partial failure stops remaining steps. There is no automatic rollback.')) != QMessageBox.Yes: return
        if time.monotonic() - self.preview_at > 30:
            self.invalidate(); self.status.setPlainText(tr('Preflight expired while awaiting confirmation. Check again.')); return
        try:
            policy = self.policy()
            credentials = {}
            for step in self.preview_steps:
                if step['ip'] not in policy['allowed'] or step['ip'] in policy['protected']:
                    raise ValueError('Target authorization changed')
                saved = self.atlas.access.credentials('http://' + step['ip'])
                credentials[step['ip']] = saved[1] if saved else ''
            steps = self.preview_steps
            self.preview_steps = None
            self.start_job(ScenarioJob(steps=steps, credentials=credentials, parent=self.atlas), self.executed)
        except (OSError, ValueError, PermissionError) as exc: self.status.setPlainText(str(exc))

    def executed(self, results):
        lines = [f'{r["ip"]} / output {r["output"]}: {r["result"]}' for r in results]
        self.status.setPlainText(('\n'.join(lines) + tr('\nUnlisted remaining destinations were not changed by this run.')))
        for line in lines: self.atlas.record('Scenario: ' + line)
