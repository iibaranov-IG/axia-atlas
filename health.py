"""Read-only engineering evidence; no device operations or inferred root causes."""
import json
import time
import zipfile
from datetime import datetime
from pathlib import Path

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


def export_report(path, snapshot, devices, changes, events):
    # Exclusive creation: never replace an existing diagnostic report.
    with Path(path).open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, value in [('health', snapshot), ('inventory', devices),
                                ('changes', changes), ('events', events)]:
                archive.writestr(name + '.json', json.dumps(value, ensure_ascii=False, indent=2))
            archive.writestr('README.txt',
                'Axia Atlas diagnostic snapshot\n'
                'Health covers only the selected channel at export time. Counters cover the listening session.\n'
                'Inventory includes saved observations: consult last_seen and inspection_at.\n'
                'Events include the current in-memory timeline (up to 5000 entries).\n'
                'No audio recording is included. Export recordings separately from Audio Monitor.\n'
                'Packet gaps do not establish a root cause. No device settings were changed.\n')


class HealthPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Selected channel health · measured evidence'))
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)
        self.export = QPushButton('Export Diagnostic Report…')
        self.export.clicked.connect(self.save_report)
        layout.addWidget(self.export)
        layout.addWidget(QLabel('ZIP: measurements, saved inventory, changes and current events. No audio included.'))
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        layout.addWidget(QLabel('Change history · latest 200 observations'))
        layout.addWidget(self.history)
        self.signature = None

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
        path, _ = QFileDialog.getSaveFileName(self, 'Export Diagnostic Report',
            'Atlas-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip', 'ZIP (*.zip)')
        if not path:
            return
        try:
            snapshot = audio_snapshot(self.atlas.player)
            snapshot['history_error'] = self.atlas.changes.error
            export_report(path, snapshot, self.atlas.inventory.devices,
                          self.atlas.changes.records, self.atlas.log.records)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Report not saved', str(exc))
            return
        self.atlas.record('Diagnostic report exported: ' + path)
        QMessageBox.information(self, 'Diagnostic Report', 'Report saved. No audio recording is included.')
