import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from PySide6.QtCore import QUrl, QEventLoop, QTimer
from PySide6.QtGui import QPdfWriter, QPainter
from PySide6.QtWidgets import QApplication
from PySide6.QtPdf import QPdfDocument
from document_viewer import DocumentViewer
from resources import CATALOG, ResourceLibrary, ResourceNavigator
from library_inventory import catalog_for
from library_downloads import files_for


class DocumentLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_inventory_models_drive_both_lists_and_specific_firmware(self):
        devices = [{'ip': '192.0.2.1', 'device_type': 'LiveMic'}]
        entries = catalog_for(CATALOG, devices)
        self.assertEqual(len(entries), 2)
        firmware = next(e for e in entries if e['kind'] == 'Firmware')
        self.assertEqual(len(files_for(firmware)), 1)
        self.assertIn('axiamic_', files_for(firmware)[0]['url'])
        for widget in (ResourceLibrary(), ResourceNavigator()):
            widget.set_devices(devices)
            tree = widget.table if isinstance(widget, ResourceLibrary) else widget.tree
            self.assertEqual(tree.topLevelItemCount(), 2 if isinstance(widget, ResourceLibrary) else 1)
            widget.set_devices([])
            self.assertEqual(tree.topLevelItemCount(), 0)
            widget.close()
        self.assertEqual(catalog_for(CATALOG, [{'ip': '192.0.2.2', 'device_type': 'Unknown'}]), [])
        xnode = catalog_for(CATALOG, [{'ip': '192.0.2.3', 'device_type': 'axiaxnode.mic'}])
        self.assertTrue(all(not e['family'].startswith('Legacy') and e['family'] != 'xNode2' for e in xnode))

    def test_pdf_local_and_remote_html_link_render_inside_atlas(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'manual.pdf'
            writer = QPdfWriter(str(path))
            painter = QPainter(writer)
            painter.drawText(100, 400, 'Atlas fixture manual')
            painter.end()
            del writer
            content = path.read_bytes()
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    pdf = self.path.startswith('/manual.pdf')
                    body = content if pdf else b'<html><title>Fixture library</title><a href="/manual.pdf" target="_blank">Manual</a></html>'
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf' if pdf else 'text/html')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                def log_message(self, *_): pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            viewer = DocumentViewer()
            viewer.show()
            try:
                viewer.open(QUrl.fromLocalFile(str(path)))
                self.assertEqual(viewer.pdf.pageCount(), 1)
                self.assertFalse(viewer.pdf.render(0, __import__('PySide6.QtCore', fromlist=['QSize']).QSize(300, 400)).isNull())
                loop = QEventLoop()
                viewer.web.loadFinished.connect(loop.quit)
                viewer.open(QUrl(f'http://127.0.0.1:{server.server_port}/'))
                QTimer.singleShot(5000, loop.quit)
                loop.exec()
                self.assertEqual(viewer.web.title(), 'Fixture library')
                viewer.pdf.statusChanged.connect(lambda status: loop.quit() if status == QPdfDocument.Status.Ready else None)
                with patch('resources.QDesktopServices.openUrl') as external:
                    viewer.web.page().runJavaScript("document.querySelector('a').click()")
                    QTimer.singleShot(5000, loop.quit)
                    loop.exec()
                    self.assertEqual(viewer.stack.currentWidget(), viewer.pdf_view)
                    self.assertEqual(viewer.pdf.pageCount(), 1)
                    self.assertTrue(viewer.property('document_url').endswith('/manual.pdf'))
                    external.assert_not_called()
            finally:
                viewer.dispose()
                viewer.close()
                self.app.processEvents()
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
