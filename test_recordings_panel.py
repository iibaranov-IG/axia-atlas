import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from recordings_panel import RecordingsPanel


class RecordingsPanelTests(unittest.TestCase):
    def test_persistent_history_reports_missing_files_and_actual_playback(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / 'recording.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                output.writeframes(bytes(48000 * 4))
            Path(str(path) + '.json').write_text(json.dumps({'source': {'channel': 9901, 'name': 'Program 1'},
                'duration_seconds': 1, 'missing_audio_frames': 4800}), encoding='utf-8')
            settings = QSettings(str(folder / 'settings.ini'), QSettings.IniFormat)
            panel = RecordingsPanel(settings)
            panel.output.setVolume(0)
            panel.add_file(path)
            panel.add_file(path)
            self.assertEqual(panel.table.topLevelItemCount(), 1)
            self.assertIn('10.0%', panel.table.topLevelItem(0).text(4))
            requested = []
            panel.playback_requested.connect(lambda: requested.append(True))
            panel.play_selected()
            loop = QEventLoop()
            QTimer.singleShot(400, loop.quit)
            loop.exec()
            self.assertEqual(panel.media.error(), QMediaPlayer.NoError)
            self.assertGreater(panel.media.duration(), 0)
            self.assertEqual(requested, [True])
            panel.media.stop()
            panel.media.setSource('')
            with patch('recordings_panel.QDesktopServices.openUrl', return_value=True) as opened:
                panel.open_folder()
                self.assertEqual(Path(opened.call_args.args[0].toLocalFile()).resolve(), folder.resolve())
            second = RecordingsPanel(settings)
            self.assertEqual(second.paths, [str(path.resolve())])
            missing = folder / 'missing.mp3'
            second.add_file(missing)
            self.assertFalse(second.play_button.isEnabled())
            self.assertEqual(second.table.currentItem().text(4), 'File unavailable')
            panel.close()
            second.close()
