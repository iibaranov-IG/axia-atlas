import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from audio_monitor import AudioBuffer
from health import ChangeHistory, audio_snapshot, export_report
from main import Atlas


class HealthTests(unittest.TestCase):
    def test_corrupt_history_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'changes.jsonl'
            path.write_text('{broken', encoding='utf-8')
            history = ChangeHistory(path)
            self.assertTrue(history.error)
            history.add('192.0.2.1', 'name', 'A', 'B', 'test')
            self.assertEqual(path.read_text(encoding='utf-8'), '{broken')

    def test_no_stream_is_not_silence_and_loss_not_output_failure(self):
        buffer = AudioBuffer()
        player = SimpleNamespace(source={}, receiver=SimpleNamespace(buffer=buffer), output_underruns=0)
        self.assertEqual(audio_snapshot(player, 100)['sound'], 'Not measured')
        buffer.last_packet = 100
        buffer.packets, buffer.gaps = 60, 40
        result = audio_snapshot(player, 100.1)
        self.assertEqual(result['missing_percent'], 40)
        self.assertEqual(result['output_underruns'], 0)
        self.assertEqual(result['stream'], 'Receiving')
        self.assertEqual(audio_snapshot(player, 101)['sound'], 'Not measured')

    def test_changes_persist_without_duplicate_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'changes.jsonl'
            history = ChangeHistory(path)
            history.compare('192.0.2.1', {}, {'name': 'A'}, 'test')
            history.compare('192.0.2.1', {'name': 'A'}, {'name': 'A'}, 'test')
            self.assertEqual(history.records, [])
            history.compare('192.0.2.1', {'name': 'A'}, {'name': 'B'}, 'test')
            self.assertEqual(ChangeHistory(path).records[0]['before'], 'A')

    def test_desktop_export_button_contains_current_evidence(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                window.show()
                window.tabs.setCurrentWidget(window.health)
                app.processEvents()
                self.assertIn('Not monitored', window.health.summary.toPlainText())
                path = Path(directory) / 'report.zip'
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')), \
                     patch.object(QMessageBox, 'information'):
                    window.health.export.click()
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(json.loads(archive.read('health.json'))['stream'], 'Not monitored')
                    self.assertIn('No audio recording', archive.read('README.txt').decode())
                with self.assertRaises(FileExistsError):
                    export_report(path, {}, {}, [], [])
            finally:
                window.close()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
