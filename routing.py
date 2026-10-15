"""Bounded LWRP destination observations and evidence-based signal paths."""
from localization import tr
import ipaddress
import json
import socket
import time
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QTabWidget)
from device_reader import attributes


def parse_destinations(raw):
    version, destinations, ended = None, {}, False
    for line in raw.decode('utf-8', errors='replace').splitlines():
        if line.startswith('ERROR'):
            raise ValueError('Device rejected the destination status query: ' + line[:200])
        if line.startswith('VER '):
            version = attributes(line[4:])
        elif line == 'END':
            ended = True
        elif line.startswith('DST '):
            parts = line.split(None, 2)
            if len(parts) != 3:
                raise ValueError('Incomplete destination indication')
            slot = int(parts[1])
            if not 1 <= slot <= 4096 or slot in destinations:
                raise ValueError('Invalid or duplicate destination slot')
            fields = attributes(parts[2])
            address = fields.get('ADDR', '').split(' ', 1)[0]
            if address not in ('', '0'):
                host, _, port = address.partition(':')
                ipaddress.IPv4Address(host)
                if port and not 1 <= int(port) <= 65535:
                    raise ValueError('Invalid destination UDP port')
            destinations[slot] = dict(slot=slot, name=fields.get('NAME', ''), address=address,
                                      fields=fields)
    if not version or 'DEVN' not in version or 'NDST' not in version:
        raise ValueError('Device did not report destination capabilities')
    expected = int(version['NDST'].split('/')[0])
    if not 0 <= expected <= 4096:
        raise ValueError('Invalid destination count')
    return dict(version=version, destinations=list(destinations.values()),
                complete=(ended or expected == 0) and len(destinations) == expected,
                observed_at=datetime.now().astimezone().isoformat(), raw=raw.hex())


def read_destinations(address, source_address=None, port=93, deadline_seconds=4):
    address = str(ipaddress.IPv4Address(address))
    deadline = time.monotonic() + deadline_seconds
    raw = bytearray()
    with socket.create_connection((address, port), timeout=min(2, deadline_seconds),
            source_address=(source_address, 0) if source_address else None) as connection:
        connection.settimeout(.2)
        connection.sendall(b'VER\r\nDST\r\n')
        while time.monotonic() < deadline:
            try:
                data = connection.recv(8192)
            except socket.timeout:
                continue
            if not data:
                break
            raw.extend(data)
            if len(raw) > 262144:
                raise ValueError('Destination response too large')
            if b'END\r\n' in raw or b'END\n' in raw:
                result = parse_destinations(raw)
                if result['complete']:
                    return result
    return parse_destinations(raw)


def stream_key(address):
    host, _, port = address.partition(':')
    return host, int(port or 5004)


def signal_paths(devices, observations):
    sources = {}
    for device in devices.values():
        for source in device.get('inspection_sources', device.get('sources', [])):
            if source.get('multicast') and source.get('enabled') is not False:
                sources.setdefault(stream_key(source['multicast']), []).append(dict(source, ip=device['ip']))
    rows = []
    for address, observation in observations.items():
        for destination in observation['destinations']:
            matches = sources.get(stream_key(destination['address']), []) if destination['address'] not in ('', '0') else []
            rows.append(dict(receiver=address, destination=destination, sources=matches,
                             observed_at=observation['observed_at'], complete=observation['complete']))
    return rows


class DestinationJob(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, address, parent=None):
        super().__init__(parent)
        self.address = address

    def run(self):
        try:
            self.result.emit(read_destinations(self.address))
        except (ValueError, OSError) as exc:
            self.failed.emit(str(exc))


class SignalPathPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.job = None
        self.path = atlas.data_dir / 'state' / 'destination-observations.json'
        self.observations = {}
        layout = QVBoxLayout(self)
        self.views = QTabWidget()
        layout.addWidget(self.views)

        known = QWidget()
        known_layout = QVBoxLayout(known)
        known_layout.addWidget(QLabel(tr('Confirmed studio signal map · supplied by engineering · not live telemetry')))
        self.map_search = QLineEdit()
        self.map_search.setPlaceholderText(tr('Find channel, source, device or purpose…'))
        self.map_search.textChanged.connect(self.render_known)
        known_layout.addWidget(self.map_search)
        self.known_tree = QTreeWidget()
        self.known_tree.setRootIsDecorated(False)
        self.known_tree.setAlternatingRowColors(True)
        self.known_tree.setHeaderLabels([tr('Channel'), tr('Source'), tr('Destination / input'), tr('Purpose'), tr('Evidence')])
        self.known_tree.setColumnWidth(0, 95)
        self.known_tree.setColumnWidth(1, 245)
        self.known_tree.setColumnWidth(2, 265)
        self.known_tree.setColumnWidth(3, 270)
        known_layout.addWidget(self.known_tree)
        self.known_status = QLabel()
        self.known_status.setWordWrap(True)
        known_layout.addWidget(self.known_status)
        self.views.addTab(known, tr('Studio Map'))

        observed = QWidget()
        observed_layout = QVBoxLayout(observed)
        observed_layout.addWidget(QLabel(tr('Observed destination assignments · not proof of audible output')))
        self.devices = QComboBox()
        self.devices.addItems(sorted(atlas.inventory.devices, key=ipaddress.ip_address))
        observed_layout.addWidget(self.devices)
        self.refresh_button = QPushButton(tr('Read Selected Device Destinations'))
        self.refresh_button.clicked.connect(self.read)
        observed_layout.addWidget(self.refresh_button)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([tr('Source / channel'), tr('Multicast'), tr('Receiver / output'), tr('Observed'), tr('Evidence')])
        observed_layout.addWidget(self.tree)
        self.status = QLabel(tr('Only an explicit refresh contacts the selected device.'))
        self.status.setWordWrap(True)
        observed_layout.addWidget(self.status)
        self.views.addTab(observed, tr('Observed Destinations'))
        try:
            if self.path.exists():
                self.observations = json.loads(self.path.read_text(encoding='utf-8'))
            self.render_known()
            self.render()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.observations = {}
            self.status.setText((tr('Saved observations could not be read: ') + str(exc)))
            self.refresh_button.setEnabled(False)

    def render_known(self):
        self.known_tree.clear()
        query = self.map_search.text().casefold().strip()
        rows = self.atlas.studio_map.topology_rows()
        shown = 0
        for row in rows:
            input_label = row['target_name'] + (f" · {row['target_input']}" if row['target_input'] else '')
            text = ' '.join(str(row.get(key, '')) for key in ('channel', 'source_name', 'target_name', 'target_input', 'purpose', 'link_type'))
            if query and query not in text.casefold():
                continue
            evidence = row['origin'] + ' · ' + row['confidence']
            self.known_tree.addTopLevelItem(QTreeWidgetItem([
                row['channel'] or '—', row['source_name'], input_label, row['purpose'], evidence]))
            shown += 1
        self.known_status.setText(tr('{v0} confirmed links shown. Relationships not listed here are unknown, not absent.', v0=shown))

    def read(self):
        if self.job or not self.atlas.access.allowed('network') or not self.devices.currentText():
            return
        address = self.devices.currentText()
        self.job = DestinationJob(address, self.atlas)
        self.atlas.jobs.append(self.job)
        self.refresh_button.setEnabled(False)
        self.status.setText(tr('Reading destination assignments…'))
        self.job.result.connect(lambda result: self.received(address, result))
        self.job.failed.connect(lambda error: self.status.setText((tr('Read failed; previous observations retained. ') + error)))
        self.job.finished.connect(self.finished)
        self.job.start()

    def received(self, address, result):
        self.observations[address] = result
        try:
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.observations, indent=2), encoding='utf-8')
            temporary.replace(self.path)
            self.render()
            self.status.setText((tr('Destinations read. ') + (tr('Complete response.') if result['complete'] else tr('Partial response; missing outputs are unknown.'))))
            self.atlas.record('Destination assignments observed', ip=address)
        except (ValueError, OSError) as exc:
            self.status.setText((tr('Could not save observations: ') + str(exc)))

    def finished(self):
        self.atlas.jobs.remove(self.job)
        self.job.deleteLater()
        self.job = None
        self.refresh_button.setEnabled(self.atlas.access.allowed('network'))

    def render(self):
        self.tree.clear()
        for row in signal_paths(self.atlas.inventory.devices, self.observations):
            sources = row['sources']
            label = ('Unknown source' if not sources else
                     f'{sources[0].get("name", "")} / {sources[0].get("channel", "—")} / {sources[0]["ip"]}' if len(sources) == 1 else
                     f'Ambiguous: {len(sources)} advertised sources')
            dest = row['destination']
            item = QTreeWidgetItem([label, dest['address'], f'{row["receiver"]} / {dest["slot"]} {dest["name"]}',
                                   row['observed_at'], 'Saved assignment; audio unverified' + ('' if row['complete'] else ' · partial device response')])
            self.tree.addTopLevelItem(item)
