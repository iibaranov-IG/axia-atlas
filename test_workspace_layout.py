import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from main import Atlas

class WorkspaceLayoutTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_player_only_audio_and_panel_operations_preserve_work(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Atlas(folder);w.show();self.app.processEvents()
   try:
    w.prompt.setPlainText('Unsent question')
    w.assistant_dock.hide()
    with patch.object(w.player,'stop') as stop, patch.object(w.player,'stop_recording') as stop_recording:
     for index in range(5):
      w.left_tabs.setCurrentIndex(index)
      self.assertEqual(w.player.isVisible(),index==1)
     w.chrome.focus.trigger()
     self.assertTrue(w.network_dock.isHidden());self.assertTrue(w.assistant_dock.isHidden())
     w.chrome.focus.trigger()
     self.assertFalse(w.network_dock.isHidden());self.assertTrue(w.assistant_dock.isHidden())
     w.chrome.toggle(1);self.assertFalse(w.assistant_dock.isHidden())
     w.chrome.toggle(0);self.assertTrue(w.network_dock.isHidden())
     w.chrome.toggle(0);self.assertFalse(w.network_dock.isHidden())
     self.assertEqual(w.prompt.toPlainText(),'Unsent question')
     stop.assert_not_called();stop_recording.assert_not_called()
    w.tabs.setCurrentIndex(1);w.navigate('home');self.assertEqual(w.tabs.currentIndex(),0)
   finally:w.close();self.app.processEvents()
 def test_badge_indicates_recording_and_returns_to_audio(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Atlas(folder)
   try:
    w.player.source=dict(channel=9901)
    w.player.recorder=object()
    w.chrome.update_badge()
    self.assertFalse(w.chrome.badge.isHidden())
    self.assertIn('9901',w.chrome.badge.text())
    self.assertTrue(w.chrome.badge.text().startswith('●'))
    w.chrome.badge.click()
    self.assertEqual(w.left_tabs.currentIndex(),1)
    self.assertIs(w.tabs.currentWidget(),w.audio_details)
   finally:w.player.recorder=None;w.player.source=None;w.close();self.app.processEvents()

 def test_pdf_page_buttons_navigate_and_stop_at_bounds(self):
  from pathlib import Path
  from PySide6.QtGui import QPdfWriter, QPainter
  from PySide6.QtCore import QUrl
  from document_viewer import DocumentViewer
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'two-pages.pdf'
   writer=QPdfWriter(str(path));painter=QPainter(writer)
   painter.drawText(100,300,'Page one');writer.newPage();painter.drawText(100,300,'Page two')
   painter.end();del writer
   viewer=DocumentViewer()
   try:
    viewer.open(QUrl.fromLocalFile(str(path)))
    self.assertEqual(viewer.pdf.pageCount(),2)
    self.assertFalse(viewer.previous_page.isEnabled())
    viewer.next_page.click()
    self.assertEqual(viewer.pdf_view.pageNavigator().currentPage(),1)
    self.assertFalse(viewer.next_page.isEnabled())
    viewer.previous_page.click()
    self.assertEqual(viewer.pdf_view.pageNavigator().currentPage(),0)
   finally:
    from PySide6.QtCore import QCoreApplication, QEvent
    viewer.dispose();viewer.close();viewer.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    self.app.processEvents()
