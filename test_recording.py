import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from audio_monitor import AudioBuffer, CompactPlayer
from recording import WaveRecorder
from test_audio_events import packet


class RecordingTests(unittest.TestCase):
    def test_finalized_wave_preserves_pcm_timing_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.wav'
            source = {'ip': '192.0.2.1', 'channel': 1301, 'multicast': '239.192.5.21'}
            recorder = WaveRecorder(path, source)
            buffer = AudioBuffer()
            buffer.recorder = recorder
            buffer.feed(packet(1, 0))
            buffer.feed(packet(3, 2))
            buffer.feed(packet(3, 2))  # duplicates must not enter the file
            self.assertTrue(recorder.stop())
            with wave.open(str(path), 'rb') as result:
                self.assertEqual(result.getparams()[:4], (2, 2, 48000, 3))
                self.assertEqual(result.readframes(3), b'\xff\x7f\x00\x80' + bytes(4) + b'\xff\x7f\x00\x80')
            report = json.loads(Path(str(path) + '.json').read_text())
            self.assertEqual(report['source']['channel'], 1301)
            self.assertEqual(report['duration_seconds'], 3 / 48000)
            self.assertEqual(report['missing_audio_frames'], 1)
            self.assertEqual(report['error'], '')
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                WaveRecorder(path, source)
            self.assertEqual(path.read_bytes(), before)

    def test_record_button_stop_and_source_switch_finalize_distinct_files(self):
        app = QApplication.instance() or QApplication([])
        player = CompactPlayer(lambda: None)
        player.show()
        app.processEvents()
        source1 = dict(ip='192.0.2.1', name='Studio A', channel=1301,
                       slot=1, multicast='239.192.5.21', channels=2)
        source2 = dict(source1, name='Studio B', channel=1302, slot=2, multicast='239.192.5.22')
        player.select(source1)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'one.wav'
            second = Path(directory) / 'two.wav'
            third = Path(directory) / 'source-change.wav'
            # The receiver fixture feeds identified, deterministic PCM to the real UI.
            # Real Windows output/network reception is verified separately on the node.
            player.receiver = MagicMock()
            player.receiver.buffer = AudioBuffer()
            with patch('audio_monitor.QFileDialog.getSaveFileName', return_value=(str(first), 'Wave audio (*.wav)')):
                QTest.mouseClick(player.record_button, Qt.LeftButton)
            self.assertEqual(player.record_button.text(), 'Stop Recording')
            recorder = player.recorder
            player.receiver.buffer.feed(packet())
            self.assertIs(recorder, player.recorder)
            # Local volume must never scale recording PCM.
            player.volume.setValue(0)
            QTest.mouseClick(player.record_button, Qt.LeftButton)
            self.assertTrue(recorder.finished)
            self.assertIsNone(player.recorder)
            self.assertIsNone(player.receiver.buffer.recorder)
            self.assertIsNotNone(player.receiver)  # Stop Recording keeps monitoring alive
            self.assertEqual(player.state.text(), 'Ready · press Play')
            player.start_recording(third)
            player.receiver.buffer.feed(packet(2, 1))
            player.select(source2)
            self.assertIsNone(player.recorder)
            self.assertIsNone(player.receiver)
            original = third.read_bytes()
            player.receiver = MagicMock()
            player.receiver.buffer = AudioBuffer()
            player.start_recording(second)
            player.receiver.buffer.feed(packet(1, 0, 10))
            player.stop()
            self.assertEqual(third.read_bytes(), original)
            self.assertEqual(json.loads(Path(str(second) + '.json').read_text())['source']['channel'], 1302)
            with wave.open(str(first), 'rb') as result:
                self.assertEqual(result.readframes(1), b'\xff\x7f\x00\x80')
            self.assertEqual(player.record_path.toolTip(), str(second.resolve()))
        player.close()
        app.processEvents()

    def test_stream_discontinuity_and_size_limit_finalize_with_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'discontinuity.wav'
            recorder = WaveRecorder(path, {})
            recorder.feed(bytes(480 * 4), 0)
            recorder.feed(bytes(480 * 4), 1_000_000)
            self.assertFalse(recorder.stop())
            self.assertIn('discontinuity', recorder.error)
            self.assertTrue(recorder.finished)
            with wave.open(str(path), 'rb') as result:
                self.assertEqual(result.getnframes(), 480)
            path = Path(directory) / 'size-limit.wav'
            recorder = WaveRecorder(path, {})
            recorder.MAX_BYTES = 4
            recorder.feed(bytes(8), 0)
            self.assertFalse(recorder.stop())
            self.assertIn('size limit', recorder.error)
            with wave.open(str(path), 'rb') as result:
                self.assertEqual(result.getnframes(), 0)

    def test_empty_recording_is_a_readable_zero_frame_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.wav'
            recorder = WaveRecorder(path, {})
            self.assertTrue(recorder.stop())
            with wave.open(str(path), 'rb') as result:
                self.assertEqual(result.getnframes(), 0)


if __name__ == '__main__':
    unittest.main()
