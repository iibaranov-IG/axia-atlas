"""Explicit --self-test mode: generated fixtures and loopback only, no real inventory."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QEventLoop, QTimer, QUrl, QSize
from PySide6.QtGui import QPdfWriter, QPainter
import lameenc
import numpy as np
import soxr
from app_paths import VERSION


def run(app, output):
    from main import Atlas
    from access_control import protect, AccessStore
    from access_server import AccountServer, RemoteAccess
    from document_viewer import DocumentViewer
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks = {}
    window = viewer = server = account_server = store = None
    code = 1
    temporary = tempfile.TemporaryDirectory(dir=output)
    try:
        root = Path(temporary.name)
        window = Atlas(root / 'app')
        window.show()
        app.processEvents()
        assert window.tabs.count() == 5
        checks['desktop'] = True
        assert protect(protect(b'build-fixture'), decrypt=True) == b'build-fixture'
        store = AccessStore(root / 'central.sqlite3')
        store.setup('build-director', 'Build-fixture-123!')
        account_server = AccountServer(root / 'central.sqlite3', root / 'tls', port=0)
        account_server.start()
        remote = RemoteAccess(f'https://127.0.0.1:{account_server.port}', account_server.fingerprint)
        remote.login('build-director', 'Build-fixture-123!')
        assert remote.user['director']
        remote.logout()
        checks['dpapi_and_https_accounts'] = True
        path = root / 'manual.pdf'
        writer = QPdfWriter(str(path))
        painter = QPainter(writer)
        painter.drawText(100, 400, 'Axia Atlas build verification: searchable reference document.')
        painter.end()
        del writer
        viewer = DocumentViewer(window)
        window.tabs.addTab(viewer, 'Build verification')
        window.tabs.setCurrentWidget(viewer)
        viewer.open(QUrl.fromLocalFile(str(path)))
        assert viewer.pdf.pageCount() == 1
        assert not viewer.pdf.render(0, QSize(300, 400)).isNull()
        checks['pdf'] = True
        entry=dict(title='Build verification manual',family='Test only',url='https://example.test/fixture.pdf',source_page='https://example.test',applicability='Synthetic verification')
        window.manuals.ingest(path,entry)
        assert window.manuals.search('verification')[0]['page']==1
        window.open_manuals()
        panel=window.tabs.currentWidget()
        panel.query.setText('verification');panel.search()
        assert panel.results.topLevelItemCount()==1
        panel.open_item()
        assert window.tabs.currentWidget().pdf.pageCount()==1
        checks['manual_knowledge'] = True
        assert window.station.data is None
        assert window.studio_map.topology_rows() == []
        assert not window.discovery_active and not window.inventory.devices
        assert window.left_tabs.tabText(0) == 'Сеть'
        window.open_station()
        station_panel=window.tabs.currentWidget()
        station_panel.kind.setCurrentIndex(1)
        assert station_panel.table.topLevelItemCount() == 0
        checks['clean_russian_first_run'] = True
        from faster_whisper import WhisperModel
        assert WhisperModel is not None
        checks['speech_recognition_runtime'] = True
        from PySide6.QtCore import QProcess
        worker = QProcess()
        command = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).with_name('main.py'))]
        worker.start(command[0], command[1:] + ['--transcribe-worker', 'transcribe', str(root/'model'), str(root/'absent.wav')])
        assert worker.waitForFinished(30000), 'Transcription worker did not finish'
        response = bytes(worker.readAllStandardOutput()).decode('utf-8')
        assert worker.exitCode() == 1 and json.loads(response)['kind'] == 'error', response
        checks['transcription_worker_reports_missing_input'] = True
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = b'<html><title>Atlas build fixture</title><h1>Loopback document</h1></html>'
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        loop = QEventLoop()
        viewer.web.loadFinished.connect(loop.quit)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(15000)
        viewer.open(QUrl(f'http://127.0.0.1:{server.server_port}/'))
        loop.exec()
        timer.stop()
        assert viewer.web.title() == 'Atlas build fixture'
        checks['webengine'] = True
        samples = np.zeros((4800, 2), dtype=np.float32)
        assert len(soxr.resample(samples, 48000, 44100)) == 4410
        encoder = lameenc.Encoder()
        encoder.set_in_sample_rate(48000)
        encoder.set_channels(2)
        encoder.set_bit_rate(192)
        encoded = encoder.encode(bytes(4800 * 4)) + encoder.flush()
        assert len(encoded) > 0
        checks['resampling_and_mp3'] = True
        code = 0
    except Exception:
        (output / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        if window:
            window.close()
        if account_server:
            account_server.stop()
        if server:
            server.shutdown()
            server.server_close()
        if store:
            store.db.close()
        app.processEvents()
        temporary.cleanup()
        (output / 'self-test.json').write_text(json.dumps(
            {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)), 'passed': code == 0, 'checks': checks}, indent=2), encoding='utf-8')
    return code
