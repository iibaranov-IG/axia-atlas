"""Synthetic protocol fixtures and loopback-only receive-to-inventory verification."""
import tempfile
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtWidgets import QApplication
from discovery import parse_advertisement
from inventory import Inventory
from main import Atlas


def number(key, value, kind=1):
    return key.encode() + bytes([kind]) + value.to_bytes({0: 1, 1: 4, 6: 2, 7: 1, 8: 2}[kind], 'big')


def text(key, value):
    raw = value.encode() + b'\0'
    return key.encode() + b'\x03' + len(raw).to_bytes(2, 'big') + raw


def block(key, content):
    return number(key, len(content), 6) + content


def advertisement(full=True, version=1):
    terminal = number('INIP', 0x7f000001) + number('ADVV', version) + number('NUMS', 1, 8)
    if full:
        terminal += text('ATRN', 'Local fixture')
    source = number('PSID', 1301) + number('FSID', 0xefc00515) + text('PSNM', 'Test source')
    return (b'\x03\x00\x02\x07' + b'\0' * 12 + number('PVER', 2, 8)
            + number('ADVT', 1 if full else 2, 7) + block('TERM', terminal)
            + (block('S001', source) if full else b''))


class DiscoveryTests(unittest.TestCase):
    def test_full_and_summary_preserve_provenance(self):
        full = parse_advertisement(advertisement(), '127.0.0.1')
        self.assertEqual(full['sources'][0], {'slot': 1, 'channel': 1301,
            'name': 'Test source', 'multicast': '239.192.5.21'})
        with tempfile.TemporaryDirectory() as directory:
            store = Inventory(Path(directory) / 'inventory.json')
            store.observe(full, 'first')
            summary = parse_advertisement(advertisement(False), '127.0.0.1')
            current = store.observe(summary, 'second')
            self.assertEqual(current['name'], 'Local fixture')
            self.assertTrue(current['sources_current'])
            changed = store.observe(parse_advertisement(advertisement(False, 2), '127.0.0.1'), 'third')
            self.assertFalse(changed['sources_current'])
            self.assertEqual(changed['sources_packet_hex'], full['packet_hex'])
            store.save()
            restored = Inventory(store.path)
            restored.load()
            self.assertEqual(restored.devices, store.devices)

    def test_reject_truncation_and_mismatched_sender(self):
        raw = advertisement()
        for length in range(len(raw)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                parse_advertisement(raw[:length], '127.0.0.1')
        with self.assertRaises(ValueError):
            parse_advertisement(raw, '192.0.2.1')
        with self.assertRaises(ValueError):
            parse_advertisement(raw + b'TEST\xff', '127.0.0.1')

    def test_loopback_packet_reaches_ui_timeout_stop_restart(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            window.queue_inspection = Mock()
            window.show()
            receiver = window.receiver
            self.assertTrue(receiver.socket.bind(QHostAddress.LocalHost, 0))
            window.discovery_active = True
            sender = QUdpSocket()
            loop = QEventLoop()
            receiver.observed.connect(lambda _: loop.quit())
            sender.writeDatagram(advertisement(), QHostAddress.LocalHost, receiver.socket.localPort())
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
            self.assertEqual(len(window.network.devices()), 1)
            item = window.network.devices()[0]
            self.assertIn('Local fixture', item.text(0))
            self.assertEqual(item.childCount(), 1)
            self.assertIn('1301', item.child(0).text(0))
            self.assertEqual(item.text(1), 'Seen')
            self.assertIn('audio unverified', item.toolTip(1))
            with patch('main.time.monotonic', return_value=window.observed_times['127.0.0.1'] + 161):
                window.discovery_tick()
                self.assertEqual(item.text(1), 'Timed out')
                window.discovery_tick()
                self.assertEqual(window.log.toPlainText().count('Announcement timeout:'), 1)
            window.toggle_discovery()
            self.assertEqual(item.text(1), 'Saved')
            window.close()
            restored = Atlas(directory)
            self.assertEqual(len(restored.network.devices()), 1)
            self.assertFalse(restored.discovery_active)
            self.assertEqual(restored.network.devices()[0].text(1), 'Saved')
            restored.close()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
