import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QAction
from main import Atlas
from broadcast_player.launcher import launch


class PlayerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_source_and_packaged_launch_have_separate_process_entry_points(self):
        with patch('broadcast_player.launcher.QProcess.startDetached', return_value=(True, 123)) as start:
            self.assertEqual(launch(), (True, 123))
            self.assertEqual(start.call_args.args[1], ['-m', 'broadcast_player'])
            self.assertEqual(Path(start.call_args.args[2]), Path(__file__).resolve().parent)
            with patch.object(sys, 'frozen', True, create=True):
                launch()
            self.assertEqual(start.call_args.args[1], ['--broadcast-player'])

    def test_atlas_menu_launch_checks_audio_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                actions = window.findChildren(QAction)
                action = next(a for a in actions if a.text() == 'ATLAS Broadcast Player…')
                with patch('broadcast_player.launcher.launch', return_value=(True, 123)) as start:
                    with patch.object(window.access, 'allowed', return_value=False):
                        action.trigger()
                    start.assert_not_called()
                    with patch.object(window.access, 'allowed', return_value=True):
                        action.trigger()
                    start.assert_called_once()
                self.assertIn('Broadcast Player opened', window.log.toPlainText())
                self.assertFalse(window.discovery_active)
            finally:
                window.close()
                self.app.processEvents()
