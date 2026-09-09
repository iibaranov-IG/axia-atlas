import os
import threading
import unittest
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QInputDialog
from main import Atlas, device_url


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<html><title>Local test node</title><h1>Local test node</h1><a href="/sources">Sources</a></html>')

    def log_message(self, *args):
        pass


class DesktopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_address_validation(self):
        self.assertEqual(device_url('192.0.2.1'), 'http://192.0.2.1/')
        self.assertEqual(device_url('::1'), 'http://[::1]/')
        for invalid in ['javascript:alert(1)', 'example.com/path', '999.0.0.1']:
            with self.assertRaises(ValueError):
                device_url(invalid)

    def test_real_desktop_workflow(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window = Atlas(temporary.name)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.tabs.count(), 5)
        self.assertEqual([window.left_tabs.tabText(i) for i in range(3)], ['Network', 'Audio', 'Library'])
        for index in range(3):
            window.left_tabs.setCurrentIndex(index)
            self.assertTrue(window.player.isVisible())
        window.tabs.setCurrentIndex(1)
        window.tasks_audio.click()
        self.assertIs(window.tabs.currentWidget(), window.audio_details)
        self.assertEqual(window.left_tabs.currentIndex(), 1)
        self.assertFalse(window.nav[0].isEnabled())
        with patch.object(QInputDialog, 'getText', return_value=('127.0.0.1', True)):
            window.add_device()
            window.add_device()
        self.assertEqual(len(window.network.devices()), 1)
        self.assertEqual(window.network.devices()[0].text(1), 'Unknown')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            from PySide6.QtCore import Qt
            item = window.network.devices()[0]
            item.setData(0, Qt.UserRole, f'http://127.0.0.1:{server.server_port}/')
            window.open_device(item)
            browser = window.tabs.currentWidget()
            loop = QEventLoop()
            results = []
            browser.loadFinished.connect(lambda ok: (results.append(ok), loop.quit()))
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            self.assertTrue(results and results[-1], 'Embedded browser must load local HTTP page')
            self.assertEqual(browser.title(), 'Local test node')
            browser.setUrl(QUrl(f'http://127.0.0.1:{server.server_port}/sources'))
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            self.assertTrue(browser.history().canGoBack())
            window.navigate('back')
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            self.assertEqual(browser.url().path(), '/')
            window.open_device(item)
            self.assertEqual(window.tabs.count(), 6)
            window.network_dock.hide()
            window.reset_layout()
            self.assertTrue(window.network_dock.isVisible())
            window.close_tab(window.fixed_tabs)
            self.assertEqual(window.tabs.count(), 5)
            window.close_tab(0)
            self.assertEqual(window.tabs.count(), 5)
            window.tabs.setCurrentIndex(0)
            self.app.processEvents()
            if os.environ.get('ATLAS_PREVIEW'):
                window.grab().save(os.environ['ATLAS_PREVIEW'])
        finally:
            server.shutdown()
            server.server_close()
            window.close()


if __name__ == '__main__':
    unittest.main()
