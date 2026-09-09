import base64
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtWidgets import QApplication
from main import Atlas


class DeviceAuthTests(unittest.TestCase):
    def test_browser_authentication_after_xnode_style_redirect(self):
        app = QApplication.instance() or QApplication([])
        accepted = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<html><meta http-equiv="refresh" content="0;url=/protected"></html>')
                elif self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'fixture:local-test').decode():
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Basic realm="Test node"')
                    self.end_headers()
                else:
                    accepted.append(True)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<html><title>Authenticated node</title>Configuration<a href="/protected/settings">Settings</a></html>')
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                window = Atlas(folder)
                url = f'http://127.0.0.1:{server.server_port}/'
                item = window.network.ensure_device(url, {'ip':'127.0.0.1', 'name':'Auth fixture'})
                with patch('device_auth.request_credentials', return_value=('fixture','local-test')) as prompt:
                    window.open_device(item)
                    browser = window.tabs.currentWidget()
                    loop = QEventLoop()
                    browser.loadFinished.connect(lambda ok: loop.quit() if ok and browser.title()=='Authenticated node' else None)
                    QTimer.singleShot(10000, loop.quit)
                    loop.exec()
                    self.assertTrue(accepted)
                    self.assertEqual(browser.title(), 'Authenticated node')
                    self.assertEqual(prompt.call_args.args[2], 'Test node')
                    browser.loadFinished.connect(loop.quit)
                    browser.page().runJavaScript("document.querySelector('a').click()")
                    QTimer.singleShot(10000, loop.quit)
                    loop.exec()
                    self.assertEqual(browser.url().path(), '/protected/settings')
                    self.assertGreaterEqual(len(accepted), 2)
                window.close_tab(window.fixed_tabs)
                window.close()
                app.processEvents()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
