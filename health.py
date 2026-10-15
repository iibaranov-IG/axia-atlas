"""Read-only engineering evidence; no device operations or inferred root causes."""
from localization import tr
import json
import time
import zipfile
import copy
import uuid
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QTimer
from recording import WaveRecorder

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFileDialog, QMessageBox)


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def audio_snapshot(player, now=None):
    result = {'observed_at': stamp(), 'source': player.source,
              'scope': 'Selected channel only', 'cause': 'Not established'}
    if not player.receiver:
        return dict(result, stream='Not monitored', sound='Not measured')
    now = time.monotonic() if now is None else now
    buffer = player.receiver.buffer
    with buffer.lock:
        values = {key: getattr(buffer, key) for key in (
            'packets', 'gaps', 'invalid', 'late', 'overflows', 'last_packet', 'left', 'right', 'error')}
    recent = bool(values['last_packet'] and now - values['last_packet'] < .5)
    result.update(values)
    result['stream'] = 'Receiving' if recent else 'No recent compatible packets'
    result['sound'] = ('Above -60 dBFS' if max(values['left'], values['right']) > -60
                       else 'At or below -60 dBFS') if recent else 'Not measured'
    result['level_note'] = 'Instantaneous sample; sustained silence and clipping are not measured.'
    result['missing_percent'] = 100 * values['gaps'] / max(1, values['packets'] + values['gaps'])
    result['output_underruns'] = player.output_underruns
    result['counter_scope'] = 'Current listening session; sequence gaps are not proof of network root cause.'
    result.pop('last_packet')
    return result


class ChangeHistory:
    fields = ('name', 'firmware', 'sources', 'inspection_sources')

    def __init__(self, path):
        self.path = Path(path)
        self.records = []
        self.error = ''
        if self.path.exists():
            try:
                for line in self.path.read_text(encoding='utf-8').splitlines():
                    record = json.loads(line)
                    if not isinstance(record, dict) or not all(key in record for key in ('time', 'ip', 'field', 'before', 'after', 'origin')):
                        raise ValueError('Unsupported change record')
                    self.records.append(record)
            except (OSError, ValueError) as exc:
                self.error = f'History unavailable; original file preserved: {exc}'

    def compare(self, address, before, after, origin):
        for field in self.fields:
            # Initial observations establish a baseline, not a change.
            if field in before and field in after and before[field] != after[field]:
                self.add(address, field, before[field], after[field], origin)

    def add(self, address, field, before, after, origin):
        if self.error:
            return
        record = dict(time=stamp(), ip=address, field=field, before=before, after=after, origin=origin)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.records.append(record)


def export_report(path, snapshot, devices, changes, events, audio_path=None, topology=None, equipment=None):
    audio_files = []
    if audio_path:
        audio_path = Path(audio_path)
        for file, name in ((audio_path, 'test-audio.wav'), (Path(str(audio_path) + '.json'), 'test-audio-report.json')):
            if file.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('Diagnostic audio exceeds the size limit')
            audio_files.append((name, file.read_bytes()))
    # Exclusive creation: never replace an existing diagnostic report.
    with Path(path).open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, value in [('health', snapshot), ('inventory', devices),
                                ('changes', changes), ('events', events)]:
                archive.writestr(name + '.json', json.dumps(value, ensure_ascii=False, indent=2))
            archive.writestr('studio-map.json', json.dumps(topology or [], ensure_ascii=False, indent=2))
            archive.writestr('equipment-cards.json', json.dumps(equipment or [], ensure_ascii=False, indent=2))
            for name, data in audio_files:
                archive.writestr(name, data)
            archive.writestr('README.txt',
                'Axia Atlas diagnostic snapshot\n'
                'Health covers only the selected channel at export time. Counters cover the listening session.\n'
                'Inventory includes saved observations: consult last_seen and inspection_at.\n'
                'Studio map contains confirmed engineering relationships, not live telemetry.\n'
                'Equipment cards are local engineering records and may include management addresses.\n'
                'Events include the current in-memory timeline (up to 5000 entries).\n'
                + ('Test audio and its capture report are included; inspect reported gaps.\n' if audio_files else
                   'No audio recording is included. Export recordings separately from Audio Monitor.\n') +
                'Packet gaps do not establish a root cause. No device settings were changed.\n')


class HealthPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.capture = None
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(100)
        self.capture_timer.timeout.connect(self.capture_tick)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Selected channel health · measured evidence')))
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)
        self.export = QPushButton(tr('Export Diagnostic Report…'))
        self.export.clicked.connect(self.save_report)
        layout.addWidget(self.export)
        self.capture_button = QPushButton(tr('Capture 10 Seconds and Export Report…'))
        self.capture_button.clicked.connect(self.start_capture)
        layout.addWidget(self.capture_button)
        self.capture_status = QLabel(tr('Test capture uses the current live source and does not stop your normal recording.'))
        self.capture_status.setWordWrap(True)
        layout.addWidget(self.capture_status)
        layout.addWidget(QLabel(tr('ZIP: measurements, saved inventory, changes and current events. No audio included.')))
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        layout.addWidget(QLabel(tr('Change history · latest 200 observations')))
        layout.addWidget(self.history)
        self.signature = None

    def start_capture(self):
        if self.capture or not all(self.atlas.access.allowed(p) for p in ('diagnostics', 'record', 'audio')):
            return
        player = self.atlas.player
        if not player.receiver:
            self.capture_status.setText(tr('Start monitoring the desired source first.'))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Capture and Export Diagnostic Report'),
            'Atlas-audio-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip', 'ZIP (*.zip)')
        if not path:
            return
        if Path(path).exists():
            self.capture_status.setText(tr('Choose a new filename; existing reports are never overwritten.'))
            return
        folder = self.atlas.data_dir / 'state' / 'diagnostic-audio'
        folder.mkdir(parents=True, exist_ok=True)
        try:
            recorder = WaveRecorder(folder / (uuid.uuid4().hex + '.wav'), copy.deepcopy(player.source), sample_width=3, input_width=3)
            receiver = player.receiver
            with receiver.buffer.lock:
                receiver.buffer.recording_taps.append(recorder)
            self.capture = dict(recorder=recorder, receiver=receiver, path=path, started=time.monotonic(), source=copy.deepcopy(player.source))
            self.capture_button.setEnabled(False)
            self.capture_status.setText(tr('Capturing test audio…'))
            self.capture_timer.start()
        except (OSError, ValueError) as exc:
            self.capture_status.setText((tr('Capture could not start: ') + str(exc)))

    def capture_tick(self):
        if not self.capture:
            return
        if not all(self.atlas.access.allowed(p) for p in ('diagnostics', 'record', 'audio')):
            self.cancel_capture('Capture cancelled: permission changed.')
            return
        if self.atlas.player.receiver is not self.capture['receiver']:
            self.cancel_capture('Capture cancelled: monitored source changed or playback stopped. Partial audio retained locally.')
            return
        if time.monotonic() - self.capture['started'] < 10:
            return
        capture = self.capture
        snapshot = audio_snapshot(self.atlas.player)
        self.cancel_capture('Finalizing diagnostic report…')
        recorder = capture['recorder']
        if recorder.error or recorder.duration_seconds == 0:
            self.capture_status.setText((tr('No report exported: ') + recorder.error or 'No compatible audio received.'))
            return
        try:
            export_report(capture['path'], snapshot, self.atlas.inventory.devices,
                          self.atlas.changes.records, self.atlas.log.records, recorder.path,
                          topology=self.atlas.studio_map.topology_rows(),
                          equipment=self.atlas.devices_nav.store.cards())
            self.capture_status.setText((tr('Report saved with test audio: ') + capture['path']))
            self.atlas.record('Diagnostic report with test audio exported: ' + capture['path'])
        except (OSError, ValueError) as exc:
            self.capture_status.setText((tr('Report not saved: ') + str(exc)))

    def cancel_capture(self, message='Diagnostic capture stopped.'):
        self.capture_timer.stop()
        if self.capture:
            capture, self.capture = self.capture, None
            with capture['receiver'].buffer.lock:
                capture['receiver'].buffer.recording_taps.remove(capture['recorder'])
            capture['recorder'].stop()
        self.capture_button.setEnabled(True)
        self.capture_status.setText(message)

    def refresh(self):
        state = audio_snapshot(self.atlas.player)
        source = state.get('source') or {}
        lines = [f'Observed: {state["observed_at"]}',
                 f'Source: {source.get("name", "Not selected")} · channel {source.get("channel", "—")} · {source.get("ip", "—")}',
                 f'Stream: {state["stream"]}', f'Audio level: {state["sound"]}']
        if 'packets' in state:
            lines.extend([f'Received packets: {state["packets"]}',
                f'Sequence gaps: {state["gaps"]} ({state["missing_percent"]:.1f}%)',
                f'Output underruns: {state["output_underruns"]}',
                f'Unsupported packets: {state["invalid"]}',
                f'Receiver error: {state["error"] or "None reported"}',
                state['level_note'], state['counter_scope']])
        lines.append('Root cause: not established. Other channels are not measured.')
        if self.atlas.changes.error:
            lines.append(self.atlas.changes.error)
        self.summary.setPlainText('\n'.join(lines))
        records = self.atlas.changes.records
        if self.signature != len(records):
            self.signature = len(records)
            self.history.setPlainText('\n\n'.join(
                f'{r["time"]} · {r["ip"]} · {r["field"]} ({r["origin"]})\n'
                f'Before: {r["before"]}\nAfter: {r["after"]}' for r in reversed(records[-200:])))

    def save_report(self):
        if not self.atlas.access.allowed('diagnostics'):
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Export Diagnostic Report'),
            'Atlas-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip', 'ZIP (*.zip)')
        if not path:
            return
        try:
            snapshot = audio_snapshot(self.atlas.player)
            snapshot['history_error'] = self.atlas.changes.error
            export_report(path, snapshot, self.atlas.inventory.devices,
                          self.atlas.changes.records, self.atlas.log.records,
                          topology=self.atlas.studio_map.topology_rows(),
                          equipment=self.atlas.devices_nav.store.cards())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr('Report not saved'), str(exc))
            return
        self.atlas.record('Diagnostic report exported: ' + path)
        QMessageBox.information(self, tr('Diagnostic Report'), tr('Report saved. No audio recording is included.'))
