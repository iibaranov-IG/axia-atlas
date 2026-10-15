"""Versioned read-only LWRP snapshots. Raw responses are never replayed as commands."""
from localization import tr
import difflib
import ipaddress
import json
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QPlainTextEdit, QSpinBox, QCheckBox)
from device_reader import parse_response, attributes
from routing import parse_destinations


def read_section(address, command, port=93):
    if command not in ('VER', 'SET', 'SRC', 'DST', 'IP', 'MTR ICH', 'MTR OCH'):
        raise ValueError('Unsupported read-only section')
    address = str(ipaddress.IPv4Address(address))
    with socket.create_connection((address, port), timeout=2) as connection:
        connection.settimeout(.2)
        connection.sendall((command + '\r\n').encode('ascii'))
        raw = bytearray()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try: data = connection.recv(8192)
            except socket.timeout:
                if raw and command in ('VER', 'SET', 'IP'): break
                continue
            if not data: break
            raw.extend(data)
            if len(raw) > 262144: raise ValueError('Section exceeds snapshot size limit')
            if b'END\n' in raw or b'END\r\n' in raw: break
        if not raw: raise ValueError('No section response')
        if any(line.startswith(b'ERROR') for line in raw.splitlines()):
            raise ValueError('Device does not provide this section to the current read-only connection')
        return bytes(raw)


def capture_snapshot(address, reader=read_section):
    address = str(ipaddress.IPv4Address(address))
    snapshot = dict(schema=1, ip=address, captured_at=datetime.now().astimezone().isoformat(),
                    scope='Reported LWRP configuration only; not a firmware image or a guaranteed full-device backup',
                    sections={}, errors={})
    version = reader(address, 'VER')
    lines = [line[4:] for line in version.decode('utf-8', errors='replace').splitlines() if line.startswith('VER ')]
    if len(lines) != 1 or not attributes(lines[0]).get('DEVN'):
        raise ValueError('Device did not return a valid identity')
    snapshot['sections']['VER'] = version.hex()
    for command in ('SET', 'SRC', 'DST', 'IP'):
        try: snapshot['sections'][command] = reader(address, command).hex()
        except (ValueError, OSError) as exc: snapshot['errors'][command] = str(exc)
    for command, parser, key in [('SRC', parse_response, 'inspection_complete'), ('DST', parse_destinations, 'complete')]:
        if command in snapshot['sections']:
            try:
                parsed = parser(version + bytes.fromhex(snapshot['sections'][command]))
                if not parsed[key]: snapshot['errors'][command] = 'Partial section response'
            except ValueError as exc: snapshot['errors'][command] = str(exc)
    return snapshot


def snapshot_text(snapshot):
    lines = [snapshot['ip'], snapshot['scope']]
    for section, raw in sorted(snapshot['sections'].items()):
        lines.extend(['[' + section + ']', bytes.fromhex(raw).decode('utf-8', errors='replace')])
    lines.extend(f'{key}: {value}' for key, value in snapshot['errors'].items())
    return '\n'.join(lines)


class BackupJob(QThread):
    completed = Signal(object)
    failed = Signal(str)
    def __init__(self, address, parent=None):
        super().__init__(parent)
        self.address = address
    def run(self):
        try: self.completed.emit(capture_snapshot(self.address))
        except (ValueError, OSError) as exc: self.failed.emit(str(exc))


class BackupsPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.job = None
        self.folder = atlas.data_dir / 'state' / 'configuration-snapshots'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.next_due = 0
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Configuration snapshots · reported LWRP sections · incomplete sections remain explicit')))
        self.devices = QComboBox()
        self.devices.addItems(sorted(atlas.inventory.devices, key=ipaddress.ip_address))
        layout.addWidget(self.devices)
        self.capture = QPushButton(tr('Save New Snapshot'))
        self.capture.clicked.connect(self.start)
        layout.addWidget(self.capture)
        row = QHBoxLayout()
        self.schedule = QCheckBox(tr('Repeat while this tab is open'))
        self.interval = QSpinBox()
        self.interval.setRange(1, 10080)
        self.interval.setValue(60)
        self.schedule.toggled.connect(lambda _: self.reset_due())
        self.interval.valueChanged.connect(lambda _: self.reset_due())
        row.addWidget(self.schedule)
        row.addWidget(self.interval)
        row.addWidget(QLabel(tr('minutes · selected device')))
        layout.addLayout(row)
        self.older = QComboBox()
        self.newer = QComboBox()
        layout.addWidget(self.older)
        layout.addWidget(self.newer)
        compare = QPushButton(tr('Compare Selected Versions'))
        compare.clicked.connect(self.compare)
        layout.addWidget(compare)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        self.status = QLabel(tr('No automatic restoration. Snapshots may omit unsupported device sections.'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.reload()

    def reset_due(self):
        self.next_due = time.monotonic() + self.interval.value() * 60

    def tick(self):
        if not self.atlas.access.allowed('backups'):
            self.schedule.setChecked(False)
        if self.schedule.isChecked() and not self.job and time.monotonic() >= self.next_due:
            self.reset_due()
            self.start()

    def start(self):
        if self.job or not self.devices.currentText() or not self.atlas.access.allowed('backups') or not self.atlas.access.allowed('network'): return
        address = self.devices.currentText()
        policy_path = self.atlas.data_dir / 'state' / 'operation-policy.json'
        try:
            policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
            if address in policy.get('protected', []):
                self.status.setText(tr('This target is excluded by the local deployment policy.')); return
        except (OSError, ValueError) as exc:
            self.status.setText((tr('Cannot read local deployment policy: ') + str(exc))); return
        self.job = BackupJob(address, self.atlas)
        self.atlas.jobs.append(self.job)
        self.job.completed.connect(self.saved)
        self.job.failed.connect(lambda error: self.status.setText((tr('Snapshot failed: ') + error)))
        self.job.finished.connect(self.finished)
        self.capture.setEnabled(False)
        self.status.setText(tr('Reading configuration sections…'))
        self.job.start()

    def saved(self, snapshot):
        path = self.folder / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.json')
        try:
            with path.open('x', encoding='utf-8') as output: json.dump(snapshot, output, ensure_ascii=False, indent=2)
            self.reload()
            self.text.setPlainText(snapshot_text(snapshot))
            self.status.setText((tr('Snapshot saved') + (tr(' with unavailable or partial sections.') if snapshot['errors'] else tr(' for all requested sections. Full-device coverage is not guaranteed.'))))
            self.atlas.record(self.status.text(), ip=snapshot['ip'])
        except (OSError, ValueError) as exc: self.status.setText((tr('Snapshot not saved: ') + str(exc)))

    def finished(self):
        self.atlas.jobs.remove(self.job)
        self.job.deleteLater()
        self.job = None
        self.capture.setEnabled(self.atlas.access.allowed('backups'))

    def reload(self):
        self.older.clear(); self.newer.clear()
        for path in sorted(self.folder.glob('*.json')):
            for combo in (self.older, self.newer): combo.addItem(path.stem, str(path))
        self.newer.setCurrentIndex(self.newer.count() - 1)
        self.older.setCurrentIndex(max(0, self.older.count() - 2))

    def compare(self):
        try:
            if not self.older.currentData() or not self.newer.currentData(): return
            old, new = [json.loads(Path(c.currentData()).read_text(encoding='utf-8')) for c in (self.older, self.newer)]
            if old['ip'] != new['ip']: raise ValueError('Select two snapshots from the same device')
            diff = difflib.unified_diff(snapshot_text(old).splitlines(), snapshot_text(new).splitlines(),
                                        fromfile=old['captured_at'], tofile=new['captured_at'], lineterm='')
            self.text.setPlainText('\n'.join(diff) or 'No differences in captured configuration sections.')
        except (OSError, ValueError, KeyError) as exc: self.status.setText((tr('Comparison unavailable: ') + str(exc)))
