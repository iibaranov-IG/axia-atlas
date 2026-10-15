"""Read-only driver capabilities, sources, destinations and optional LWRP meters."""
from localization import tr
import re
from datetime import datetime
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QPlainTextEdit
from backups import read_section
from device_reader import attributes, parse_response
from routing import parse_destinations


def read_driver(address, reader=read_section):
    raw = reader(address, 'VER')
    versions = [attributes(line[4:]) for line in raw.decode(errors='replace').splitlines() if line.startswith('VER ')]
    if len(versions) != 1: raise ValueError('No valid device identity')
    version = versions[0]
    if not ('lwwd' in version.get('DEVN', '').lower() or 'driver' in version.get('DEVN', '').lower()):
        raise ValueError('Selected device does not identify as an IP Driver')
    result = dict(ip=address, observed_at=datetime.now().astimezone().isoformat(), identity=version,
                  sources=[], destinations=[], meters=[], unavailable={})
    for command in ('SRC', 'DST', 'MTR ICH', 'MTR OCH'):
        try:
            section = reader(address, command)
            if command == 'SRC':
                parsed = parse_response(raw + section)
                result['sources'] = parsed['inspection_sources']
                if not parsed['inspection_complete']: result['unavailable'][command] = 'Partial response'
            elif command == 'DST':
                parsed = parse_destinations(raw + section)
                result['destinations'] = parsed['destinations']
                if not parsed['complete']: result['unavailable'][command] = 'Partial response'
            else:
                meters = []
                for line in section.decode(errors='replace').splitlines():
                    match = re.fullmatch(r'MTR (ICH|OCH) (\d+) PEEK:(-?\d+):(-?\d+) RMS:(-?\d+):(-?\d+)', line)
                    if match:
                        direction, slot, *levels = match.groups()
                        meters.append(dict(direction=direction, slot=int(slot), levels=[int(x) / 10 for x in levels]))
                if not meters: raise ValueError('No supported meter indications returned')
                result['meters'].extend(meters)
        except (ValueError, OSError) as exc: result['unavailable'][command] = str(exc)
    return result


class DriverJob(QThread):
    completed = Signal(object)
    failed = Signal(str)
    def __init__(self, address, parent=None):
        super().__init__(parent)
        self.address = address
    def run(self):
        try: self.completed.emit(read_driver(self.address))
        except (ValueError, OSError) as exc: self.failed.emit(str(exc))


class DriverPanel(QWidget):
    def __init__(self, atlas, address=''):
        super().__init__()
        self.atlas, self.job = atlas, None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('IP Driver diagnostics · device-reported values · explicit refresh')))
        self.devices = QComboBox()
        for ip, device in atlas.inventory.devices.items():
            kind = device.get('device_type', '').lower()
            if 'lwwd' in kind or 'driver' in kind: self.devices.addItem(ip)
        if address:
            index = self.devices.findText(address)
            if index >= 0:
                self.devices.setCurrentIndex(index)
        layout.addWidget(self.devices)
        self.refresh_button = QPushButton(tr('Read Driver State'))
        self.refresh_button.clicked.connect(self.read)
        layout.addWidget(self.refresh_button)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        self.text.setPlainText(tr('Select an identified IP Driver. Unsupported details will remain unavailable.'))

    def read(self):
        if self.job or not self.devices.currentText() or not all(self.atlas.access.allowed(p) for p in ('network', 'diagnostics')): return
        self.job = DriverJob(self.devices.currentText(), self.atlas)
        self.atlas.jobs.append(self.job)
        self.job.completed.connect(self.render)
        self.job.failed.connect(lambda text: self.text.setPlainText((tr('Read failed: ') + text)))
        self.job.finished.connect(self.finished)
        self.refresh_button.setEnabled(False)
        self.text.setPlainText(tr('Reading driver capabilities and channel state…'))
        self.job.start()

    def render(self, result):
        identity = result['identity']
        lines = [f'{result["ip"]} · observed {result["observed_at"]}',
                 f'Type: {identity.get("DEVN")} · version: {identity.get("SYSV", identity.get("SVER", "Unknown"))}',
                 '\nTransmit sources:']
        lines += [f'  {s["slot"]}: {s["name"]} · channel {s["channel"] or "unassigned"} · enabled {s["enabled"]}' for s in result['sources']]
        lines.append('\nReceive destinations:')
        lines += [f'  {d["slot"]}: {d["name"]} ← {d["address"] or "unassigned"}' for d in result['destinations']]
        lines.append('\nReported levels (dBFS; snapshot, not continuous):')
        lines += [f'  {"Input" if m["direction"] == "ICH" else "Output"} {m["slot"]}: peak L/R {m["levels"][0]:.1f}/{m["levels"][1]:.1f}, RMS L/R {m["levels"][2]:.1f}/{m["levels"][3]:.1f}' for m in result['meters']]
        lines.append('\nUnavailable:')
        lines += [f'  {k}: {v}' for k, v in result['unavailable'].items()]
        lines.append('Internal Windows driver packet/latency counters are not exposed by these LWRP queries.')
        self.text.setPlainText('\n'.join(lines))
        self.atlas.record('IP Driver status read', ip=result['ip'])

    def finished(self):
        self.atlas.jobs.remove(self.job)
        self.job.deleteLater()
        self.job = None
        self.refresh_button.setEnabled(True)
