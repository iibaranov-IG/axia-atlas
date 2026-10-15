import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtCore import QUrl,QCoreApplication,QEvent
from answer_panel import AnswerPanel
from main import Atlas

class AnswerPanelTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_long_answer_opens_once_and_clear_removes_private_tabs(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Atlas(folder)
   try:
    text='## Diagnosis\n\n|Check|Result|\n|---|---|\n|Stream|Unknown|\n\n'+'Evidence is not available. '*45
    w.chat.add_message('user','Explain the signal path')
    with patch.object(w,'launch_request') as launch:
     w.chat.add_message('assistant',text)
     panel=w.tabs.currentWidget()
     self.assertIsInstance(panel,AnswerPanel)
     self.assertEqual(panel.answer,text)
     self.assertIn(text,w.chat.toPlainText())
     self.assertLess(len(w.chat.rows[-1][2].text()),len(text))
     self.assertIsNone(w.chat.rows[-1][1].findChild(QPushButton))
     w.open_answer("Explain the signal path",text)
     self.assertIs(w.tabs.currentWidget(),panel)
     self.assertEqual(w.tabs.count(),w.fixed_tabs+1)
     launch.assert_not_called()
    w.chat.clear();self.assertEqual(w.tabs.count(),w.fixed_tabs)
   finally:
    w.close();w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);self.app.processEvents()
 def test_short_answer_has_no_button_and_inert_resources(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Atlas(folder)
   try:
    w.chat.add_message('assistant','A short answer')
    self.assertEqual(w.tabs.count(),w.fixed_tabs)
    self.assertIsNone(w.chat.rows[-1][1].findChild(QPushButton))
    w.open_answer("", "A short answer")
    panel=w.tabs.currentWidget();self.assertIsInstance(panel,AnswerPanel)
    links=[];panel.link_requested.connect(lambda *args:links.append(args))
    for target in ('file:///C:/private.txt','javascript:alert(1)','data:text/html,x'):
     panel.open_link(QUrl(target))
     self.assertIsNone(panel.browser.loadResource(2,QUrl(target)))
    self.assertEqual(links,[])
   finally:
    w.close();w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);self.app.processEvents()
