"""Receive-only Livewire discovery. No queries or configuration commands are sent.

Transport: https://docs.telosalliance.com/docs/list-of-tcp-and-udp-ports-used-for-telos-products
Experimental field interpretation: https://github.com/nick-prater/read_lw_sources
Unknown encodings are rejected rather than guessed. Device audio health is not inferred.
"""
import ipaddress
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QUdpSocket, QHostAddress, QAbstractSocket

GROUP = '239.192.255.3'
PORT = 4001


class UnsupportedAdvertisement(ValueError):
    pass


def parse_advertisement(packet, sender):
    if len(packet) < 16 or packet[:4] != b'\x03\x00\x02\x07':
        raise ValueError('Unsupported advertisement header')
    sender = str(ipaddress.IPv4Address(sender))

    def section(start, end, depth=0):
        if depth > 2:
            raise ValueError('Unexpected section nesting')
        fields = {}
        while start < end:
            if end - start < 5:
                raise ValueError('Truncated field header')
            key = packet[start:start + 4].decode('ascii', errors='strict')
            kind = packet[start + 4]
            start += 5
            if key in fields:
                raise ValueError('Duplicate field')
            sizes = {0: 1, 1: 4, 6: 2, 7: 1, 8: 2, 9: 8}
            if kind == 3:
                if start + 2 > end:
                    raise ValueError('Truncated string length')
                size = int.from_bytes(packet[start:start + 2], 'big')
                start += 2
            elif kind in sizes:
                size = sizes[kind]
            else:
                raise ValueError(f'Unsupported field encoding {kind}')
            if start + size > end:
                raise ValueError('Truncated field value')
            raw = packet[start:start + size]
            start += size
            value = raw.split(b'\0', 1)[0].decode('utf-8', errors='replace') if kind == 3 else int.from_bytes(raw, 'big')
            if depth == 0 and key == 'ADVT' and value not in (1, 2):
                raise UnsupportedAdvertisement('Non-inventory advertisement type')
            if key == 'TERM' or (key.startswith('S') and key[1:].isdigit()):
                if kind not in (6, 8) or start + value > end:
                    raise ValueError('Invalid section length')
                value, start = section(start, start + value, depth + 1)
            fields[key] = value
        return fields, start

    fields, _ = section(16, len(packet))
    if fields.get('PVER') != 2 or fields.get('ADVT') not in (1, 2):
        raise ValueError('Unsupported advertisement version or type')
    terminal = fields.get('TERM')
    if not isinstance(terminal, dict) or not isinstance(terminal.get('INIP'), int):
        raise ValueError('Missing terminal address')
    address = str(ipaddress.IPv4Address(terminal['INIP']))
    if address != sender:
        raise ValueError('Sender and advertised address differ')
    result = {'ip': address, 'name': terminal.get('ATRN', ''),
              'version': terminal.get('ADVV'), 'source_count': terminal.get('NUMS'),
              'full': fields['ADVT'] == 1, 'sources': [], 'packet_hex': packet.hex()}
    if (not isinstance(result['name'], str) or not isinstance(result['source_count'], int)
            or not isinstance(result['version'], int)):
        raise ValueError('Invalid terminal fields')
    for key, source in fields.items():
        if key.startswith('S') and key[1:].isdigit() and isinstance(source, dict):
            channel, multicast = source.get('PSID'), source.get('FSID')
            name = source.get('PSNM', '')
            if not isinstance(channel, int) or not isinstance(multicast, int) or not isinstance(name, str):
                raise ValueError('Invalid source fields')
            if not ipaddress.IPv4Address(multicast).is_multicast:
                raise ValueError('Invalid source multicast address')
            result['sources'].append({'slot': int(key[1:]), 'channel': channel,
                                      'name': name, 'multicast': str(ipaddress.IPv4Address(multicast))})
    if result['full'] and len(result['sources']) != result['source_count']:
        raise ValueError('Incomplete full advertisement')
    return result


class DiscoveryReceiver(QObject):
    observed = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.socket = QUdpSocket(self)
        self.socket.readyRead.connect(self.receive)
        self.rejected = 0
        self.received = 0
        self.ignored = 0

    def start(self, interface):
        self.stop()
        self.rejected = self.received = self.ignored = 0
        if not self.socket.bind(QHostAddress.AnyIPv4, PORT,
                QAbstractSocket.ShareAddress | QAbstractSocket.ReuseAddressHint):
            raise OSError(self.socket.errorString())
        if not self.socket.joinMulticastGroup(QHostAddress(GROUP), interface):
            message = self.socket.errorString()
            self.stop()
            raise OSError(message)

    def stop(self):
        self.socket.close()

    def receive(self):
        # Limit work per event so a busy network cannot monopolise the UI thread.
        from PySide6.QtCore import QTimer
        for _ in range(100):
            if not self.socket.hasPendingDatagrams():
                return
            datagram = self.socket.receiveDatagram(65535)
            self.received += 1
            try:
                event = parse_advertisement(bytes(datagram.data()), datagram.senderAddress().toString())
            except UnsupportedAdvertisement:
                self.ignored += 1
                continue
            except (ValueError, UnicodeError):
                self.rejected += 1
                continue
            self.observed.emit(event)
        if self.socket.hasPendingDatagrams():
            QTimer.singleShot(0, self.receive)
