"""Official file links verified against manufacturer pages on 2026-09-09."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QUrl, QSaveFile, QIODevice
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

LEGACY = 'https://telosalliance-uat.s3.amazonaws.com/public/Axia%20Products/Discontinued%20Products/'
CLASSIC = 'https://telos-support.s3.us-east-1.amazonaws.com/Axia/Nodes+(classic)/'


def files_for(entry):
    family, kind = entry['family'], entry['kind']
    pairs = []
    if family.startswith('Legacy'):
        pairs = ([('Analog / AES / Microphone manual', LEGACY + 'Audio%20Nodes/axia_analog_aes_nodes_v2.pdf'),
                  ('GPIO manual', LEGACY + 'Audio%20Nodes/axia_gpio_v2.2_12-2008.pdf')] if kind == 'Manuals' else
                 [('2001-00133 Analog · 2.7.1d r2', CLASSIC + 'axiaanlg_2_7_1d_r2.pkg'),
                  ('2001-00135 AES/EBU · 2.7.1d r2', CLASSIC + 'axiaaes_2_7_1d_r2.pkg'),
                  ('2001-00136 Microphone · 2.7.1d r1', CLASSIC + 'axiamic_2_7_1d_r1.pkg'),
                  ('2001-00007 GPIO · 2.7.1d r1', CLASSIC + 'axiagpio_2_7_1d_r1.pkg')])
    elif family.startswith('Router Selector'):
        pairs = [('Router Selector', LEGACY + ('RouterSelector_v2.5.pdf' if kind == 'Manuals' else 'axiasel_2_5_2g_r3.pkg'))]
    elif family == 'xNode (original generation)':
        pairs = [('xNode User Manual', 'https://telosalliance-uat.s3.amazonaws.com/public/Axia%20Products/xNodes/Support%20Files/Telos_Alliance_xNodes_Manual_C23519069.pdf')]
    elif family == 'xNode / xSwitch / xSelector':
        pairs = [('xNode / xSwitch / xSelector · 2.4.22', 'https://telos-support.s3.us-east-1.amazonaws.com/Axia/xNodes/1601-00506-022_xnodes_2_4_22.pkg')]
    if kind == 'Manuals' and QUrl(entry['url']).path().lower().endswith('.pdf'):
        pairs = [(entry['title'], entry['url'])]
    types = set(entry.get('detected_types', '').split('|'))
    if family.startswith('Legacy') and entry.get('detected_types'):
        if kind == 'Manuals':
            pairs = [(label, url) for label, url in pairs if
                     ('GPIO' in label and 'livegpio' in types) or
                     ('GPIO' not in label and types.intersection({'liveio', 'livemic', 'liveaes'}))]
        else:
            names = {'liveio': 'axiaanlg_', 'livemic': 'axiamic_', 'liveaes': 'axiaaes_', 'livegpio': 'axiagpio_'}
            pairs = [(label, url) for label, url in pairs if any(names[t] in url for t in types if t in names)]
    return [dict(label=label, url=url, source_page=entry['url']) for label, url in pairs]


class LibraryDownload(QObject):
    progress = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.network = QNetworkAccessManager(self)
        self.reply = None

    def path_for(self, entry):
        name = Path(QUrl(entry['url']).path()).name
        return self.folder / hashlib.sha256(entry['url'].encode()).hexdigest()[:16] / name

    def start(self, entry):
        if self.reply:
            return
        self.path = self.path_for(entry)
        self.entry = dict(entry)
        self.digest = hashlib.sha256()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.file = QSaveFile(str(self.path))
            if not self.file.open(QIODevice.WriteOnly):
                raise OSError(self.file.errorString())
        except OSError as exc:
            self.failed.emit(str(exc))
            return
        self.size = 0
        self.prefix = bytearray()
        self.problem = ''
        request = QNetworkRequest(QUrl(entry['url']))
        request.setTransferTimeout(30000)
        self.reply = self.network.get(request)
        self.reply.setReadBufferSize(1024 * 1024)
        self.reply.readyRead.connect(self.read)
        self.reply.finished.connect(self.finish)
        self.progress.emit('Downloading from the official source…')

    def read(self):
        data = bytes(self.reply.readAll())
        self.size += len(data)
        self.prefix.extend(data[:max(0, 512 - len(self.prefix))])
        self.digest.update(data)
        if self.size > 256 * 1024 * 1024:
            self.problem = 'Download exceeds the 256 MB library limit.'
            self.reply.abort()
            return
        if self.file.write(data) != len(data):
            self.problem = self.file.errorString()
            self.reply.abort()
            return
        self.progress.emit(f'Downloaded {self.size / 1048576:.1f} MB…')

    def cancel(self):
        if self.reply:
            self.problem = 'Download cancelled.'
            self.reply.abort()

    def finish(self):
        reply = self.reply
        if reply.error() == QNetworkReply.NoError:
            self.read()
        error = self.problem or (reply.errorString() if reply.error() != QNetworkReply.NoError else '')
        if not error and (not self.size or b'<html' in bytes(self.prefix).lower() or b'<!doctype html' in bytes(self.prefix).lower() or
                (self.path.suffix.lower() == '.pdf' and not self.prefix.startswith(b'%PDF-'))):
            error = 'The server did not return the expected file. Open the official page.'
        if error:
            self.file.cancelWriting()
            self.file.commit()  # close and discard the temporary file on Windows
        elif not self.file.commit():
            error = self.file.errorString()
        else:
            report = dict(self.entry, downloaded_at=datetime.now(timezone.utc).isoformat(),
                final_url=reply.url().toString(), bytes=self.size, sha256=self.digest.hexdigest())
            metadata = QSaveFile(str(self.path) + '.json')
            raw = json.dumps(report, indent=2).encode('utf-8')
            if not metadata.open(QIODevice.WriteOnly) or metadata.write(raw) != len(raw) or not metadata.commit():
                error = 'File saved, but its source report could not be saved.'
        self.file = None
        self.reply = None
        reply.deleteLater()
        if error:
            self.failed.emit(error)
        else:
            self.completed.emit(str(self.path))
