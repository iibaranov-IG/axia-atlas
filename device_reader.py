"""Bounded, read-only LWRP inventory queries. No login or configuration writes.

Telos Systems Livewire Routing Protocol v2.0.2 sections 3.1.3 and 3.2.4:
https://www.redmine.digispot.ru/attachments/download/30131/LwRtProto-2005-10-19.pdf
"""
import ipaddress
import shlex
import socket
import time
from PySide6.QtCore import QThread, Signal


def attributes(text):
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    result = {}
    for token in lexer:
        if ':' in token:
            key, value = token.split(':', 1)
            if key in result:
                raise ValueError('Duplicate response attribute')
            result[key] = value
    return result


def parse_response(raw):
    version = None
    sources = {}
    ended = False
    for line in raw.decode('utf-8', errors='replace').splitlines():
        line = line.strip()
        if line.startswith('VER '):
            version = attributes(line[4:])
        elif line == 'END':
            ended = True
        elif line.startswith('SRC '):
            pieces = line.split(None, 2)
            if len(pieces) < 2:
                raise ValueError('Incomplete source response')
            slot = int(pieces[1])
            if slot in sources or not 1 <= slot <= 4096:
                raise ValueError('Invalid or duplicate source slot')
            values = attributes(pieces[2]) if len(pieces) == 3 else {}
            address = values.get('RTPA', '0').split(':', 1)[0]
            channel = None
            if address not in ('', '0'):
                multicast = ipaddress.IPv4Address(address)
                if str(multicast).startswith('239.192.'):
                    channel = int(multicast) & 0xffff
            sources[slot] = {'slot': slot, 'channel': channel,
                'name': values.get('PSNM', ''), 'multicast': address,
                'channels': int(values.get('NCHN', '2')),
                'enabled': {'0': False, '1': True}.get(values.get('RTPE'))}
    if not version or not version.get('LWRP') or not version.get('DEVN'):
        raise ValueError('No valid LWRP version response')
    expected = int(version.get('NSRC', '0').split('/')[0])
    if expected < 0 or expected > 4096:
        raise ValueError('Invalid source count')
    complete = (ended or expected == 0) and len(sources) == expected
    return {'device_type': version['DEVN'], 'firmware': version.get('SYSV', version.get('SVER', 'Unknown')),
        'version_field': 'SYSV' if 'SYSV' in version else 'SVER' if 'SVER' in version else '',
        'product': version.get('PRODUCT', ''), 'model': version.get('MODEL', ''),
        'inspection_source_count': expected, 'inspection_sources': list(sources.values()),
        'inspection_complete': complete, 'inspection_raw': raw.hex()}


def read_device(address, source_address=None, port=93, deadline_seconds=4):
    address = str(ipaddress.IPv4Address(address))
    deadline = time.monotonic() + deadline_seconds
    chunks = bytearray()
    with socket.create_connection((address, port), timeout=min(2, deadline_seconds),
            source_address=(source_address, 0) if source_address else None) as connection:
        connection.settimeout(.25)
        connection.sendall(b'VER\r\nSRC\r\n')
        while time.monotonic() < deadline:
            try:
                data = connection.recv(8192)
            except socket.timeout:
                continue
            if not data:
                break
            chunks.extend(data)
            if len(chunks) > 262144:
                raise ValueError('Device response exceeds inventory size limit')
            # SRC status batches end in END. Some zero-source implementations only return VER.
            if b'END' in data or b'END' in chunks[-32:]:
                try:
                    result = parse_response(chunks)
                    if result['inspection_complete']:
                        return result
                except ValueError:
                    pass
    result = parse_response(chunks)
    return result


class DeviceReadJob(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, address, source_address=None, parent=None):
        super().__init__(parent)
        self.address, self.source_address = address, source_address

    def run(self):
        try:
            result = read_device(self.address, self.source_address)
            if not self.isInterruptionRequested():
                self.completed.emit(self.address, result)
        except (OSError, ValueError) as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.address, str(exc))
