import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from library_downloads import LibraryDownload, files_for
from resources import CATALOG


class DownloadTests(unittest.TestCase):
    def test_real_http_atomic_download_provenance_and_invalid_file(self):
        app = QApplication.instance() or QApplication([])
        content = b'%PDF-1.4\nfixture'
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = b'<html>Error</html>' if self.path.startswith('/bad') else content
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                job = LibraryDownload(folder)
                completed, failed = [], []
                job.completed.connect(completed.append)
                job.failed.connect(failed.append)
                def fetch(name):
                    loop = QEventLoop()
                    job.completed.connect(loop.quit)
                    job.failed.connect(loop.quit)
                    job.start({'url': f'http://127.0.0.1:{server.server_port}/{name}.pdf', 'label': name})
                    QTimer.singleShot(3000, loop.quit)
                    loop.exec()
                fetch('ok')
                self.assertEqual(len(completed), 1)
                path = Path(completed[0])
                self.assertEqual(path.read_bytes(), content)
                report = json.loads(Path(str(path)+'.json').read_text())
                self.assertEqual(report['sha256'], hashlib.sha256(content).hexdigest())
                fetch('bad')
                self.assertEqual(len(failed), 1)
                self.assertFalse(job.path.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_classic_firmware_hardware_variants_are_explicit(self):
        entry = next(e for e in CATALOG if e['family'].startswith('Legacy') and e['kind']=='Firmware')
        choices = files_for(entry)
        self.assertEqual(len(choices), 4)
        self.assertTrue(any('2001-00136' in e['label'] and e['url'].endswith('_r1.pkg') for e in choices))
