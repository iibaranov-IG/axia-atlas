"""Inventory with explicit observation provenance and atomic local persistence."""
import json
import os
from pathlib import Path


class Inventory:
    def __init__(self, path):
        self.path = Path(path)
        self.devices = {}
        self.dirty = False

    def load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema') != 1 or not isinstance(data.get('devices'), dict):
                raise ValueError('Unsupported inventory file')
            self.devices = data['devices']

    def observe(self, event, timestamp):
        old = self.devices.get(event['ip'], {})
        version_changed = old.get('version') != event['version']
        current = dict(old)
        current.update({key: value for key, value in event.items() if key not in ('sources', 'name', 'full')})
        current['name'] = event['name'] if event['full'] else (event['name'] or old.get('name', ''))
        current['last_seen'] = timestamp
        if event['full']:
            current['sources'] = event['sources']
            current['sources_seen'] = timestamp
            current['sources_current'] = True
            current['sources_packet_hex'] = event['packet_hex']
        elif version_changed:
            current['sources_current'] = False
        if version_changed and old.get('version') is not None:
            current['inspection_stale'] = True
        self.devices[event['ip']] = current
        self.dirty = True
        return current

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump({'schema': 1, 'devices': self.devices}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        self.dirty = False

    def inspected(self, address, result, timestamp):
        device = self.devices.setdefault(address, {'ip': address, 'name': ''})
        device.update(result)
        device['inspection_at'] = timestamp
        device['inspection_stale'] = False
        device.pop('inspection_error', None)
        self.dirty = True
        return device
