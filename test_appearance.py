import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from main import Atlas


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_live_switch_keeps_work_and_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            window = Atlas(folder)
            try:
                panel = window.open_scenarios()
                panel.name.setText('Unsaved routing plan')
                window.prompt.setPlainText('Unsent question')
                window.chat.add_message('user', 'Existing conversation')
                player, receiver = window.player, window.receiver
                initial_tabs = window.tabs.count()
                with patch.object(player, 'stop') as stop, patch.object(receiver, 'stop') as stop_network:
                    for skin in ('macos', 'windows', 'macos'):
                        window.skin_actions[skin].trigger()
                        self.app.processEvents()
                        self.assertEqual(window.property('atlasSkin'), skin)
                        self.assertIs(window.tabs.currentWidget(), panel)
                        self.assertEqual(window.tabs.count(), initial_tabs)
                        self.assertEqual(panel.name.text(), 'Unsaved routing plan')
                        self.assertEqual(window.prompt.toPlainText(), 'Unsent question')
                        self.assertEqual(window.chat.rows[0][2].text(), 'Existing conversation')
                        self.assertIs(window.player, player)
                        self.assertEqual(sum(a.isChecked() for a in window.skin_actions.values()), 1)
                    stop.assert_not_called(); stop_network.assert_not_called()
            finally: window.close(); self.app.processEvents()
            reopened = Atlas(folder)
            try:
                self.assertEqual(reopened.property('atlasSkin'), 'macos')
                reopened.set_appearance('unknown')
                self.assertEqual(reopened.property('atlasSkin'), 'windows')
            finally: reopened.close(); self.app.processEvents()
