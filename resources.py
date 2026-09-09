"""Curated official reference links; no claim of device compatibility or latest release."""
from pathlib import Path
from library_downloads import LibraryDownload, files_for
from library_inventory import catalog_for, inventory_note
from app_paths import application_data_dir
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QTreeWidget, QTreeWidgetItem, QPushButton, QApplication, QMessageBox)

REVIEWED = '2026-09-09'
CATALOG = [
    {'family': 'Legacy Analog / AES / Microphone / GPIO Nodes', 'kind': 'Manuals',
     'version': 'See document', 'title': 'Original Audio Nodes — manuals and downloads',
     'url': 'https://www.telosalliance.com/legacy/axia-products',
     'notes': 'Open the Original Audio Nodes section. Manuals for audio and GPIO nodes are separate.'},
    {'family': 'Legacy Analog / AES / Microphone / GPIO Nodes', 'kind': 'Firmware',
     'version': '2.7.1d · r1/r2 · Beta', 'title': 'Legacy node update — release notes and model-specific downloads',
     'url': 'https://docs.telosalliance.com/docs/updating-legacy-axia-nodes-to-eliminate-java',
     'notes': 'Official legacy listing identifies 2.7.1d.r2. Release article calls these final legacy releases Beta. '
              'Select the exact hardware part number: 2001-00133, 2001-00135, 2001-00136 or 2001-00007. '
              'Separate files per model. Not for xNode or xNode2.'},
    {'family': 'Router Selector Node (legacy)', 'kind': 'Manuals',
     'version': '2.5', 'title': 'Router Selector manual',
     'url': 'https://www.telosalliance.com/legacy/axia-products',
     'notes': 'Open the Router Selector Node section.'},
    {'family': 'Router Selector Node (legacy)', 'kind': 'Firmware',
     'version': '2.5.2g', 'title': 'Router Selector software download listing',
     'url': 'https://www.telosalliance.com/legacy/axia-products',
     'notes': 'Open the Router Selector Node section. This entry is for the legacy Router Selector, not xSelector.'},
    {'family': 'xNode (original generation)', 'kind': 'Manuals',
     'version': 'C23519069', 'title': 'xNode Installation and User Guide',
     'url': 'https://www.telosalliance.com/legacy/telos-alliance-analog-xnode',
     'notes': 'Original xNode documentation; not an xNode2 manual.'},
    {'family': 'xNode / xSwitch / xSelector', 'kind': 'Firmware',
     'version': '2.4.22', 'title': 'Software package — update instructions and release notes',
     'url': 'https://docs.telosalliance.com/docs/xnode-xswitch-and-xselector-software-package-v2422-update-instructions-release-notes',
     'notes': 'Manufacturer scope includes original xNode AES, Analog, Mic, Mixed Signal, GPIO, xSwitch and xSelector. '
              'Excludes classic nodes and xNode2. Read upgrade prerequisites on the official page.'},
    {'family': 'Axia IP Audio Driver for Windows', 'kind': 'Manuals',
     'version': 'See article', 'title': 'IP Audio Driver help library',
     'url': 'https://docs.telosalliance.com/docs/ip-audio-driver-help-documents',
     'notes': 'Vendor help library with configuration and troubleshooting articles.'},
    {'family': 'Axia IP Audio Driver for Windows', 'kind': 'Software',
     'version': '2.12.0.5', 'title': 'Driver release, installation information and download',
     'url': 'https://docs.telosalliance.com/docs/axia-ip-driver-version-21205-release-and-install-information',
     'notes': 'Vendor specifies Windows 10 or higher, 64-bit. Not this release for Windows 7 or Server 2012 R2. '
              'Read licensing and installation prerequisites on the official page.'},
    {'family': 'xNode2', 'kind': 'Manuals', 'version': 'Online manual',
     'title': 'xNode2 Manual', 'url': 'https://docs.telosalliance.com/docs/xnode2-manual',
     'notes': 'For the xNode2 generation. Hardware generation must be identified before selecting firmware.'},
]
CATALOG.extend([
    dict(family='Quasar console / engine', kind='Manuals', version='1.4.18', title='Quasar User Manual',
         url='https://www.telosalliance.com/uploads/Axia%20Products/Quasar/Assets/1490-00224-001%20Quasar%20User%20Manual%20v1.4.18.pdf',
         notes='Published Quasar manual. Some functions may differ on newer software.'),
    dict(family='Quasar console / engine', kind='Firmware', version='See release notes', title='Quasar software release notes',
         url='https://docs.telosalliance.com/docs/quasar-software-release-notes-all-versions',
         notes='Check the component compatibility matrix and update prerequisites. No automatic compatibility decision.'),
    dict(family='QOR / iQ', kind='Manuals', version='1.3.1', title='iQ Console System and QOR.32 manual',
         url='https://www.telosalliance.com/uploads/Axia%20Products/iQ/Axia-iQ%20Manual-v1.3.1-C21316028.pdf',
         notes='iQ and QOR.32 documentation. Verify the QOR hardware variant.'),
    dict(family='Omnia ONE', kind='Manuals', version='Official resources', title='Omnia ONE manuals',
         url='https://www.telosalliance.com/legacy/omnia-one', notes='Manual and quick start guide in the Resources section.'),
    dict(family='Omnia ONE', kind='Firmware', version='2.8.1', title='Omnia ONE software resources',
         url='https://www.telosalliance.com/legacy/omnia-one', notes='Separate AM, FM, Multicast, SG and Studio Pro packages. Verify the installed product variant.'),
    dict(family='Telos VX', kind='Manuals', version='Official resources', title='Telos VX documentation',
         url='https://www.telosalliance.com/legacy/telos-vx', notes='Original VX resources. Confirm hardware generation before using instructions.'),
])


class ResourceLibrary(QWidget):
    open_requested = Signal(object, str)
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel('Documentation & Firmware')
        heading.setStyleSheet('font-size: 22px; font-weight: 600; margin: 12px;')
        layout.addWidget(heading)
        note = QLabel(f'Official reference catalog · reviewed {REVIEWED}\n'
            'Listed versions are published releases, not verified upgrades for your device.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.inventory_status = QLabel()
        self.inventory_status.setWordWrap(True)
        layout.addWidget(self.inventory_status)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a model, manual or version…')
        self.kind = QComboBox()
        self.kind.addItems(['Manuals', 'Firmware', 'Software'])
        self.family = QComboBox()
        self.family.addItems(['All equipment'] + sorted({entry['family'] for entry in CATALOG}))
        row.addWidget(self.search, 1)
        row.addWidget(self.kind)
        layout.addLayout(row)
        layout.addWidget(self.family)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(['Equipment family', 'Resource', 'Version / revision'])
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 100)
        for entry in CATALOG:
            item = QTreeWidgetItem([entry['family'], entry['kind'], entry['version']])
            item.setData(0, Qt.UserRole, entry)
            self.table.addTopLevelItem(item)
        layout.addWidget(self.table, 1)
        self.details = QLabel('Select a resource to see its scope and official source.')
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.open_button = QPushButton('Open in Atlas')
        self.copy_button = QPushButton('Copy Link')
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        row.addWidget(self.open_button)
        row.addWidget(self.copy_button)
        row.addStretch()
        layout.addLayout(row)
        self.search.textChanged.connect(self.filter)
        self.kind.currentTextChanged.connect(self.filter)
        self.family.currentTextChanged.connect(self.filter)
        self.table.currentItemChanged.connect(self.select)
        self.open_button.clicked.connect(self.open_page)
        self.table.itemDoubleClicked.connect(lambda *_: self.open_page())
        self.copy_button.clicked.connect(self.copy_link)
        self.download = LibraryDownload(application_data_dir() / 'state' / 'library', self)
        self.file_choices = QComboBox()
        layout.addWidget(self.file_choices)
        download_row = QHBoxLayout()
        self.download_button = QPushButton('Download from Official Site')
        self.cancel_button = QPushButton('Cancel Download')
        self.cancel_button.setEnabled(False)
        self.local_button = QPushButton('Open Downloaded File')
        self.local_button.setEnabled(False)
        download_row.addWidget(self.download_button)
        download_row.addWidget(self.cancel_button)
        download_row.addWidget(self.local_button)
        layout.addLayout(download_row)
        self.download_status = QLabel('Select a resource to download. Firmware is saved locally; installation is separate.')
        self.download_status.setWordWrap(True)
        layout.addWidget(self.download_status)
        self.download_button.clicked.connect(self.download_selected)
        self.cancel_button.clicked.connect(self.download.cancel)
        self.download.progress.connect(self.download_status.setText)
        self.download.completed.connect(self.download_complete)
        self.download.failed.connect(self.download_failed)
        self.file_choices.currentIndexChanged.connect(self.update_local)
        self.local_button.clicked.connect(self.open_local)
        self.filter()

    def set_devices(self, devices):
        signature = repr([(d.get('ip'), d.get('device_type')) for d in devices])
        if getattr(self, '_inventory_signature', None) == signature:
            return
        self._inventory_signature = signature
        entries = catalog_for(CATALOG, devices)
        current = self.table.currentItem()
        selected = current.data(0, Qt.UserRole) if current else None
        previous = self.family.currentText()
        self.family.blockSignals(True)
        self.family.clear()
        self.family.addItems(['All discovered equipment'] + sorted({e['family'] for e in entries}))
        if self.family.findText(previous) >= 0:
            self.family.setCurrentText(previous)
        self.family.blockSignals(False)
        self.table.clear()
        for entry in entries:
            item = QTreeWidgetItem([entry['family'], entry['kind'], entry['version']])
            item.setData(0, Qt.UserRole, entry)
            self.table.addTopLevelItem(item)
        self.filter()
        if selected:
            for index in range(self.table.topLevelItemCount()):
                item = self.table.topLevelItem(index)
                entry = item.data(0, Qt.UserRole)
                if not item.isHidden() and (entry['family'], entry['kind']) == (selected['family'], selected['kind']):
                    self.table.setCurrentItem(item)
        self.inventory_status.setText(inventory_note(devices))

    def filter(self, *_):
        query = self.search.text().strip().casefold()
        kind = self.kind.currentText()
        self.table.setCurrentItem(None)
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            entry = item.data(0, Qt.UserRole)
            item.setHidden(not (query in ' '.join(entry.values()).casefold()
                and entry['kind'] == kind
                and (self.family.currentIndex() == 0 or entry['family'] == self.family.currentText())))

    def select(self, item, *_):
        self.open_button.setEnabled(item is not None)
        self.copy_button.setEnabled(item is not None)
        if hasattr(self, 'file_choices'):
            self.file_choices.clear()
            if item:
                for entry in files_for(item.data(0, Qt.UserRole)):
                    self.file_choices.addItem(entry['label'], entry)
            self.download_button.setEnabled(item is not None and self.download.reply is None and
                getattr(self, 'permission_check', lambda _: True)('downloads'))
            self.download_button.setText('Download from Official Site' if self.file_choices.count() else 'Open Official Download Page')
        if item is None:
            self.details.setText('Select a resource to see its scope and official source.')
            return
        entry = item.data(0, Qt.UserRole)
        self.details.setText(f'{entry["title"]}\n\n{entry["notes"]}\n\nSource: {entry["url"]}')

    def open_page(self):
        if not getattr(self, 'permission_check', lambda _: True)('library'):
            return
        item = self.table.currentItem()
        if item:
            entry = item.data(0, Qt.UserRole)
            chosen = self.file_choices.currentData()
            if entry['kind'] == 'Manuals' and chosen and QUrl(chosen['url']).path().lower().endswith('.pdf'):
                path = self.download.path_for(chosen)
                url = QUrl.fromLocalFile(str(path.resolve())) if path.is_file() else QUrl(chosen['url'])
            else:
                url = QUrl(entry['url'])
            self.open_requested.emit(url, entry['title'])

    def copy_link(self):
        item = self.table.currentItem()
        if item:
            QApplication.clipboard().setText(item.data(0, Qt.UserRole)['url'])

    def update_local(self, *_):
        entry = self.file_choices.currentData()
        self.local_button.setEnabled(bool(entry and self.download.path_for(entry).is_file()))
        self.local_button.setText('Open Download Folder' if entry and entry['url'].endswith('.pkg') else 'Open Downloaded File')

    def download_selected(self):
        if not getattr(self, 'permission_check', lambda _: True)('downloads'):
            self.download_status.setText('Downloads are not permitted for this account.')
            return
        entry = self.file_choices.currentData()
        if not entry:
            self.open_page()
            return
        self.download_button.setEnabled(False)
        self.file_choices.setEnabled(False)
        self.table.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.download.start(entry)

    def download_complete(self, path):
        self.download_status.setText(f'Saved locally: {path}')
        self.download_done()

    def download_failed(self, message):
        self.download_status.setText(f'Download not completed: {message}')
        self.download_done()

    def download_done(self):
        self.download_button.setEnabled(self.table.currentItem() is not None and
            getattr(self, 'permission_check', lambda _: True)('downloads'))
        self.file_choices.setEnabled(True)
        self.table.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.update_local()

    def open_local(self):
        if not getattr(self, 'permission_check', lambda _: True)('library'):
            return
        entry = self.file_choices.currentData()
        if entry:
            path = self.download.path_for(entry)
            if path.is_file():
                if path.suffix.lower() == '.pdf':
                    self.open_requested.emit(QUrl.fromLocalFile(str(path.resolve())), path.name)
                elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))):
                    self.download_status.setText('Could not open the download folder.')

    def closeEvent(self, event):
        self.download.cancel()
        super().closeEvent(event)


class ResourceNavigator(QWidget):
    selected = Signal(object)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.kind = QComboBox()
        self.kind.addItems(['Manuals', 'Firmware', 'Software'])
        layout.addWidget(self.kind)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find manual, model or firmware…')
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)
        self.inventory_status = QLabel()
        self.inventory_status.setWordWrap(True)
        layout.addWidget(self.inventory_status)
        groups = {}
        for entry in CATALOG:
            if entry['family'] not in groups:
                groups[entry['family']] = QTreeWidgetItem([entry['family']])
                self.tree.addTopLevelItem(groups[entry['family']])
            item = QTreeWidgetItem([f'{entry["kind"]} · {entry["version"]}'])
            item.setData(0, Qt.UserRole, entry)
            groups[entry['family']].addChild(item)
        self.search.textChanged.connect(self.filter)
        self.kind.currentTextChanged.connect(lambda _: self.filter(self.search.text()))
        self.tree.itemClicked.connect(self.pick)
        self.filter('')

    def set_devices(self, devices):
        signature = repr([(d.get('ip'), d.get('device_type')) for d in devices])
        if getattr(self, '_inventory_signature', None) == signature:
            return
        self._inventory_signature = signature
        expanded = {self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).isExpanded()}
        self.tree.clear()
        groups = {}
        for entry in catalog_for(CATALOG, devices):
            if entry['family'] not in groups:
                root = QTreeWidgetItem([entry['family']])
                self.tree.addTopLevelItem(root)
                root.setExpanded(entry['family'] in expanded)
                groups[entry['family']] = root
            item = QTreeWidgetItem([f'{entry["kind"]} · {entry["version"]}'])
            item.setData(0, Qt.UserRole, entry)
            groups[entry['family']].addChild(item)
        self.inventory_status.setText(inventory_note(devices))
        self.filter(self.search.text())

    def pick(self, item, _):
        if item.data(0, Qt.UserRole):
            self.selected.emit(item.data(0, Qt.UserRole))

    def filter(self, query):
        for index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(index)
            for child_index in range(root.childCount()):
                child = root.child(child_index)
                entry = child.data(0, Qt.UserRole)
                child.setHidden(entry['kind'] != self.kind.currentText() or
                    query.casefold() not in ' '.join(entry.values()).casefold())
            root.setHidden(all(root.child(i).isHidden() for i in range(root.childCount())))
            if query and not root.isHidden():
                root.setExpanded(True)
