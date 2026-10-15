"""Searchable manufacturer evidence; original PDFs stay inside Atlas."""
from localization import tr
from PySide6.QtCore import Qt,QUrl
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QPushButton,QTreeWidget,QTreeWidgetItem,QPlainTextEdit


class ManualPanel(QWidget):
    def __init__(self,host):
        super().__init__(host)
        self.host=host
        layout=QVBoxLayout(self)
        docs=host.manuals.documents()
        layout.addWidget(QLabel(tr('{v0} manuals · {v1} PDF pages · family references, check revision', v0=len(docs), v1=sum((d['page_count'] for d in docs)))))
        row=QHBoxLayout();layout.addLayout(row)
        self.family=QComboBox();self.family.addItem(tr('Automatic / All families'),None)
        for family in sorted({d['family'] for d in docs}):self.family.addItem(family,family)
        row.addWidget(self.family)
        self.query=QLineEdit();self.query.setPlaceholderText(tr('Search manuals in English or Russian…'));row.addWidget(self.query)
        button=QPushButton(tr('Search'));button.clicked.connect(self.search);row.addWidget(button)
        self.query.returnPressed.connect(self.search)
        self.results=QTreeWidget();self.results.setHeaderLabels([tr('Manual'),tr('PDF page')]);layout.addWidget(self.results)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True);layout.addWidget(self.preview)
        self.results.currentItemChanged.connect(self.show_item)
        self.results.itemDoubleClicked.connect(lambda *_:self.open_item())
        button=QPushButton(tr('Open PDF in Atlas'));button.clicked.connect(self.open_item);layout.addWidget(button)
        self.show_documents(docs)

    def show_documents(self,docs):
        for doc in docs:self.add_row(dict(doc,page=1,body=''))

    def add_row(self,row):
        item=QTreeWidgetItem([row['title'],str(row['page'])]);item.setData(0,Qt.UserRole,row);self.results.addTopLevelItem(item)

    def search(self):
        if not self.host.access_allowed('library'):return
        self.results.clear();self.preview.clear()
        if not self.query.text().strip():
            self.show_documents([d for d in self.host.manuals.documents() if not self.family.currentData() or d['family']==self.family.currentData()]);return
        for row in self.host.manuals.search(self.query.text(),self.family.currentData(),limit=12):self.add_row(row)
        if self.results.topLevelItemCount():self.results.setCurrentItem(self.results.topLevelItem(0))
        else:self.preview.setPlainText(tr('No matching passage found. Try an English term or select another equipment family.'))

    def show_item(self,item,*_):
        if not item:return
        row=item.data(0,Qt.UserRole)
        self.preview.setPlainText(tr('{v0}\n{v1}\nSource: {v2}\nSHA256: {v3}\n\n{v4}', v0=row['family'], v1=row['applicability'], v2=row['source_page'], v3=row['sha256'], v4=row['body']))

    def open_item(self):
        if not self.host.access_allowed('library'):return
        item=self.results.currentItem()
        if not item:return
        row=item.data(0,Qt.UserRole)
        self.host.open_document(QUrl.fromLocalFile(row['path']),row['title'])
        page=self.host.tabs.currentWidget()
        if hasattr(page,'page_number'):page.page_number.setValue(row['page'])
