"""Read-only answer document; never runs HTML scripts or fetches embedded resources."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTextBrowser,QLabel,QPushButton,QApplication
from localization import tr

class AnswerBrowser(QTextBrowser):
    def loadResource(self, kind, url):
        return None

class AnswerPanel(QWidget):
    link_requested=Signal(object,str)
    def __init__(self,question,answer,parent=None):
        super().__init__(parent)
        self.answer=answer
        layout=QVBoxLayout(self)
        title=QLabel(question or tr('Virtual Engineer Answer'))
        title.setTextFormat(Qt.PlainText);title.setWordWrap(True)
        layout.addWidget(title)
        row=QHBoxLayout()
        copy=QPushButton(tr('Copy answer'))
        copy.clicked.connect(lambda:QApplication.clipboard().setText(self.answer))
        row.addWidget(copy);row.addStretch();layout.addLayout(row)
        self.browser=AnswerBrowser()
        self.browser.setOpenLinks(False);self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self.open_link)
        self.browser.setMarkdown(answer)
        layout.addWidget(self.browser,1)
        note=QLabel(tr('Engineer answer · verify recommendations against the cited evidence.'))
        note.setWordWrap(True);layout.addWidget(note)
    def open_link(self,url):
        if url.scheme() in ('http','https'):
            self.link_requested.emit(url,tr('Answer reference'))
