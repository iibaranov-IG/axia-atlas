import json
import socket
import struct
import tempfile
import threading
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QFileDialog
from main import Atlas
from equipment import EquipmentStore, EquipmentPanel
from assistant_context import collect_context
from multi_health import AlarmState
from routing import parse_destinations, read_destinations, signal_paths, SignalPathPanel
from audio_monitor import AudioReceiver
from recording import WaveRecorder


class EngineeringFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_equipment_persistence_and_conflicting_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                panel = EquipmentPanel(window)
                panel.devices.setCurrentText('192.0.2.20')
                panel.load_button.click()
                panel.fields['studio'].setText('Studio A')
                panel.fields['notes'].setPlainText('Replace fan at next maintenance')
                panel.save_button.click()
                store = EquipmentStore(Path(directory) / 'state/equipment.sqlite3')
                card = store.get('192.0.2.20')
                self.assertEqual(card['studio'], 'Studio A')
                self.assertEqual(card['revision'], 1)
                values = {k: card[k] for k in panel.fields}
                with self.assertRaises(ValueError):
                    store.save('192.0.2.20', values, 0, 'Another engineer')
                self.assertEqual(len(store.history('192.0.2.20')), 1)
                self.assertEqual(window.inventory.devices, {})
            finally:
                window.close()
                self.app.processEvents()

    def test_confirmed_studio_map_is_searchable_and_separate_from_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                from test_release_fixtures import seed_studio
                seed_studio(window.studio_map)
                panel = SignalPathPanel(window)
                self.assertEqual(panel.known_tree.topLevelItemCount(), 2)
                panel.map_search.setText('12345')
                self.assertEqual(panel.known_tree.topLevelItemCount(), 1)
                self.assertEqual(panel.known_tree.topLevelItem(0).text(0), '12345')
                self.assertEqual(panel.tree.topLevelItemCount(), 0)
            finally:
                panel.close()
                window.close()
                self.app.processEvents()

    def test_context_is_explicit_bounded_and_permission_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                window.inventory.devices['192.0.2.20'] = dict(ip='192.0.2.20', name='Node A', inspection_raw='SECRET-NOT-CONTEXT')
                self.assertEqual(collect_context(window, set()), '[]')
                text = collect_context(window, {'inventory'})
                self.assertIn('Node A', text)
                self.assertNotIn('SECRET', text)
                with patch.object(window.access, 'allowed', return_value=False):
                    self.assertEqual(collect_context(window, {'inventory', 'audio', 'events'}), '[]')
            finally:
                window.close()
                self.app.processEvents()

    def test_sustained_alarm_and_single_recovery(self):
        state = AlarmState()
        self.assertEqual(state.update({'Silence': True}, 10, 3), (set(), set()))
        self.assertEqual(state.update({'Silence': True}, 12.9, 3), (set(), set()))
        self.assertEqual(state.update({'Silence': True}, 13, 3), ({'Silence'}, set()))
        self.assertEqual(state.update({'Silence': True}, 15, 3), (set(), set()))
        self.assertEqual(state.update({'Silence': False}, 16, 3), (set(), {'Silence'}))
        self.assertEqual(state.update({'Silence': False}, 17, 3), (set(), set()))

    def test_destination_reader_fragmented_loopback_and_ambiguous_source(self):
        raw = b'VER LWRP:1.1 DEVN:LiveIO NDST:1\r\nBEGIN\r\nDST 1 ADDR:"239.192.0.1" NAME:"Monitor"\r\nEND\r\n'
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        received = []
        def server():
            with listener.accept()[0] as client:
                data = b''
                while not data.endswith(b'DST\r\n'):
                    data += client.recv(100)
                received.append(data)
                client.sendall(raw[:20])
                client.sendall(raw[20:])
        thread = threading.Thread(target=server)
        thread.start()
        try:
            result = read_destinations('127.0.0.1', port=listener.getsockname()[1])
        finally:
            thread.join(5)
            listener.close()
        self.assertEqual(received, [b'VER\r\nDST\r\n'])
        self.assertTrue(result['complete'])
        devices = {ip: dict(ip=ip, sources=[dict(multicast='239.192.0.1', enabled=True)])
                   for ip in ('192.0.2.1', '192.0.2.2')}
        paths = signal_paths(devices, {'192.0.2.3': result})
        self.assertEqual(len(paths[0]['sources']), 2)
        with self.assertRaises(ValueError):
            parse_destinations(raw.replace(b'END', b'DST 1 ADDR:0\r\nEND'))

    def test_diagnostic_capture_keeps_normal_recording_and_exports_native_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            source = dict(ip='192.0.2.1', multicast='239.192.0.1', channel=1, name='Fixture', slot=1)
            window.player.source = source
            window.player.output_underruns = 0
            receiver = AudioReceiver(source, 1)
            window.player.receiver = receiver
            normal = WaveRecorder(Path(directory) / 'normal.wav', source, sample_width=3, input_width=3)
            receiver.buffer.recorder = normal
            report = Path(directory) / 'report.zip'
            try:
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(report), '')):
                    window.health.capture_button.click()
                self.assertIsNotNone(window.health.capture)
                for seq in range(100):
                    receiver.buffer.feed(struct.pack('!BBHII', 128, 96, seq, seq * 12, 1) + b'\x01\x02\x03\x04\x05\x06' * 12)
                window.health.capture['started'] -= 11
                window.health.capture_tick()
                self.assertIs(receiver.buffer.recorder, normal)
                self.assertEqual(receiver.buffer.recording_taps, [])
                with zipfile.ZipFile(report) as archive:
                    import io
                    with wave.open(io.BytesIO(archive.read('test-audio.wav'))) as audio:
                        self.assertEqual(audio.getnframes(), 1200)
                        self.assertEqual(audio.getsampwidth(), 3)
                        self.assertEqual(audio.readframes(1), b'\x03\x02\x01\x06\x05\x04')
                    evidence = json.loads(archive.read('test-audio-report.json'))
                    self.assertEqual(evidence['source']['channel'], 1)
            finally:
                receiver.buffer.recorder = None
                normal.stop()
                window.close()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
