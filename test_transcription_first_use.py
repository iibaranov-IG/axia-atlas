import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
from main import Atlas
class FirstTranscriptionTests(unittest.TestCase):
 def test_file_without_model_can_start_and_download_is_explicit(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Atlas(folder)
   try:
    p=w.open_transcription();audio=Path(folder)/'Запись.wav';audio.write_bytes(b'test')
    with patch.object(QFileDialog,'getOpenFileName',return_value=(str(audio),'')):
     p.choose_file()
    self.assertTrue(p.run_button.isEnabled())
    with patch.object(QMessageBox,'question',return_value=QMessageBox.No),patch('transcription_panel.QProcess') as process:
     p.run_button.click();process.assert_not_called()
    with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch('transcription_panel.QProcess') as process:
     p.run_button.click()
     args=process.return_value.start.call_args.args[1]
     self.assertIn('prepare_transcribe',args);self.assertIn(str(audio),args)
     self.assertFalse(p.run_button.isEnabled())
     p.process=None
   finally:w.close();app.processEvents()
