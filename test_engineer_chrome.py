import tempfile
import unittest
from PySide6.QtWidgets import QApplication, QPushButton
from main import Atlas

class EngineerChromeTests(unittest.TestCase):
 def test_settings_and_compose_controls(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   window=Atlas(folder)
   try:
    window.show();app.processEvents()
    self.assertFalse(window.engineer_settings.isVisible())
    self.assertTrue(window.prompt.isVisible())
    self.assertTrue(window.context_button.isVisible())
    window.engineer_settings_button.click();app.processEvents()
    self.assertTrue(window.connect_button.isVisible())
    self.assertTrue(window.answer_language.isVisible())
    window.engineer_settings_button.click();app.processEvents()
    self.assertFalse(window.answer_language.isVisible())
    self.assertEqual(window.context_status.text(),'')
    self.assertFalse(hasattr(window,'manual_button'))
    self.assertFalse(hasattr(window,'station_button'))
   finally:
    window.close();app.processEvents()
