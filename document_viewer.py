"""In-application HTML and PDF references; never launches external handlers."""
from pathlib import Path
from PySide6.QtCore import QUrl, QTimer, QBuffer, QIODevice, QPointF, Qt
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QSpinBox, QComboBox


class ReferencePage(QWebEnginePage):
    def __init__(self, viewer, popup=False):
        super().__init__(viewer.profile, viewer)
        self.viewer, self.popup = viewer, popup

    def acceptNavigationRequest(self, url, kind, main_frame):
        if url.scheme() not in ('http', 'https', 'about'):
            self.viewer.status.setText('This link cannot be opened as documentation.')
            return False
        if url.scheme() != 'about' and not self.viewer.allowed_reference(url):
            self.viewer.status.setText('This link is outside the documentation sources supported by Atlas.')
            return False
        if main_frame and (self.popup or url.path().lower().endswith('.pdf')):
            QTimer.singleShot(0, lambda u=QUrl(url): self.viewer.open(u))
            if self.popup:
                self.deleteLater()
            return False
        return True

    def createWindow(self, _):
        return ReferencePage(self.viewer, popup=True)


class DocumentViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.reply = None
        self.buffer = None
        self.network = QNetworkAccessManager(self)
        self.urls, self.position = [], -1
        self.initial_origin = None
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.back_button = QPushButton('Back')
        self.forward_button = QPushButton('Forward')
        self.back_button.clicked.connect(lambda: self.move(-1))
        self.forward_button.clicked.connect(lambda: self.move(1))
        row.addWidget(self.back_button)
        row.addWidget(self.forward_button)
        self.page_number = QSpinBox()
        self.page_number.setPrefix('Page ')
        self.page_number.setMinimum(1)
        self.page_number.valueChanged.connect(lambda page: self.pdf_view.pageNavigator().jump(page - 1, QPointF()))
        row.addWidget(self.page_number)
        self.zoom = QComboBox()
        self.zoom.addItems(['Fit width', 'Fit page', '100%', '150%', '200%'])
        self.zoom.currentIndexChanged.connect(self.set_zoom)
        row.addWidget(self.zoom)
        row.addStretch()
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.profile = QWebEngineProfile(self)
        self.profile.downloadRequested.connect(self.download_requested)
        self.web = QWebEngineView()
        self.web.setPage(ReferencePage(self))
        self.web.urlChanged.connect(self.remember)
        self.web.loadFinished.connect(lambda ok: self.status.setText(self.web.url().toString() if ok else 'Document page could not be loaded.'))
        self.stack.addWidget(self.web)
        self.pdf = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf.statusChanged.connect(self.pdf_status)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self.current_page)
        self.stack.addWidget(self.pdf_view)

    def current_page(self, page):
        self.page_number.blockSignals(True)
        self.page_number.setValue(page + 1)
        self.page_number.blockSignals(False)

    def set_zoom(self, index):
        if index < 2:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth if index == 0 else QPdfView.ZoomMode.FitInView)
        else:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor((1, 1.5, 2)[index - 2])

    def remember(self, url):
        if url.isEmpty() or url.toString() == 'about:blank':
            return
        if self.position < 0 or self.urls[self.position] != url:
            self.urls = self.urls[:self.position + 1] + [QUrl(url)]
            self.position = len(self.urls) - 1
        self.back_button.setEnabled(self.position > 0)
        self.forward_button.setEnabled(self.position + 1 < len(self.urls))

    def move(self, delta):
        position = self.position + delta
        if 0 <= position < len(self.urls):
            self.position = position
            self.open(self.urls[position])

    def allowed_reference(self, url):
        host = url.host().lower()
        return (host == 'telosalliance.com' or host.endswith('.telosalliance.com') or
                host in ('telosalliance-uat.s3.amazonaws.com', 'telos-support.s3.amazonaws.com',
                         'telos-support.s3.us-east-1.amazonaws.com') or
                (url.scheme(), host, url.port()) == self.initial_origin)

    def open(self, url, force_pdf=False):
        url = QUrl(url)
        if url.scheme() not in ('http', 'https', 'file'):
            self.status.setText('Unsupported document address.')
            return
        if not url.isLocalFile():
            if self.initial_origin is None:
                self.initial_origin = (url.scheme(), url.host().lower(), url.port())
            if not self.allowed_reference(url):
                self.status.setText('This link is outside the documentation sources supported by Atlas.')
                return
        self.cancel()
        self.web.stop()
        self.remember(url)
        self.setProperty('document_url', url.toString())
        is_pdf = force_pdf or url.path().lower().endswith('.pdf')
        self.page_number.setVisible(is_pdf)
        self.zoom.setVisible(is_pdf)
        self.status.setText('Opening document…')
        self.stack.setCurrentWidget(self.pdf_view if is_pdf else self.web)
        if not is_pdf:
            if url.isLocalFile():
                self.status.setText('Only PDF files are supported for local documents.')
                return
            self.web.setUrl(url)
            return
        self.pdf.close()
        if self.buffer:
            self.buffer.close()
            self.buffer.deleteLater()
        self.buffer = None
        if url.isLocalFile():
            self.pdf.load(url.toLocalFile())
        else:
            request = QNetworkRequest(url)
            request.setTransferTimeout(30000)
            self.reply = self.network.get(request)
            self.reply.setReadBufferSize(1024 * 1024)
            self.data = bytearray()
            self.reply.readyRead.connect(self.read_pdf)
            self.reply.finished.connect(self.pdf_received)

    def read_pdf(self):
        if not self.reply:
            return
        self.data.extend(bytes(self.reply.readAll()))
        if len(self.data) > 64 * 1024 * 1024:
            self.reply.abort()
            self.status.setText('Document exceeds the 64 MB viewer limit.')

    def pdf_received(self):
        if not self.reply:
            return
        self.read_pdf()
        reply, self.reply = self.reply, None
        if reply.error() != QNetworkReply.NoError or not self.data.startswith(b'%PDF-'):
            self.status.setText('PDF could not be loaded. Check the official document address or use a downloaded copy.')
        else:
            self.buffer = QBuffer(self)
            self.buffer.setData(bytes(self.data))
            self.buffer.open(QIODevice.ReadOnly)
            self.pdf.load(self.buffer)
        reply.deleteLater()
        self.data = bytearray()

    def pdf_status(self, status):
        if status == QPdfDocument.Status.Ready:
            self.page_number.setMaximum(max(1, self.pdf.pageCount()))
            self.page_number.setValue(1)
            self.status.setText(f'{self.pdf.pageCount()} pages · {self.property("document_url")}')
        elif status == QPdfDocument.Status.Error:
            self.status.setText('PDF could not be opened. It may be damaged or password protected.')

    def download_requested(self, download):
        url, mime = download.url(), download.mimeType()
        download.cancel()
        if mime == 'application/pdf' or url.path().lower().endswith('.pdf'):
            QTimer.singleShot(0, lambda: self.open(url, force_pdf=True))
        else:
            self.status.setText('Use the Library download button to save firmware or software files.')

    def cancel(self):
        if self.reply:
            reply, self.reply = self.reply, None
            reply.abort()
            reply.deleteLater()

    def dispose(self):
        self.cancel()
        self.web.stop()
        self.pdf.close()
        page = self.web.page()
        self.profile.setParent(self.parent())
        page.destroyed.connect(self.profile.deleteLater)
        page.deleteLater()
