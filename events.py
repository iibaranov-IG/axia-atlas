"""Unified application/device timeline. Raw device datagrams are retained in the archive."""
import json
import re
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtNetwork import QUdpSocket, QHostAddress, QNetworkInterface, QAbstractSocket
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QSpinBox, QCheckBox, QFileDialog, QApplication)

LEVELS = ['Emergency', 'Alert', 'Critical', 'Error', 'Warning', 'Notice', 'Info', 'Debug']


def parse_syslog(raw):
    text = raw.decode('utf-8', errors='replace')
    match = re.match(r'^<(\d{1,3})>', text)
    priority = int(match[1]) if match and int(match[1]) <= 191 else None
    return {'message': text[match.end():] if priority is not None else text,
            'severity': LEVELS[priority % 8] if priority is not None else 'Unknown',
            'facility': priority // 8 if priority is not None else None, 'raw_hex': raw.hex()}


class EventsPanel(QWidget):
    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)
        self.records = []
        self.socket = QUdpSocket(self)
        self.socket.readyRead.connect(self.receive)
        self.received = 0
        self.file_index = 0
        self.archive_error = ''
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.origin = QComboBox()
        self.origin.addItems(['All', 'Application', 'Devices'])
        self.severity = QComboBox()
        self.severity.addItems(['All severities'] + LEVELS + ['Unknown'])
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find message or device IP…')
        for widget in (self.origin, self.severity, self.search):
            row.addWidget(widget)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(['Received', 'Source', 'Device IP', 'Severity', 'Message'])
        for index, width in enumerate((170, 90, 120, 85, 550)):
            self.tree.setColumnWidth(index, width)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        self.auto_scroll = QCheckBox('Auto Scroll')
        self.auto_scroll.setChecked(True)
        self.pause = QCheckBox('Pause View')
        self.archive = QCheckBox('Auto Save')
        self.archive.setChecked(True)
        copy = QPushButton('Copy Selected')
        copy.clicked.connect(self.copy_selected)
        export = QPushButton('Export Visible…')
        export.clicked.connect(self.export_visible)
        folder = QPushButton('Open Archive')
        folder.clicked.connect(self.open_archive)
        for widget in (self.auto_scroll, self.pause, self.archive, copy, export, folder):
            row.addWidget(widget)
        layout.addLayout(row)
        self.address = QComboBox()
        self.address.addItem('All local interfaces', '0.0.0.0')
        for interface in QNetworkInterface.allInterfaces():
            for entry in interface.addressEntries():
                if entry.ip().protocol() == QAbstractSocket.IPv4Protocol:
                    self.address.addItem(f'{interface.humanReadableName()} · {entry.ip().toString()}', entry.ip().toString())
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(514)
        self.start = QPushButton('Start Device Log')
        self.start.clicked.connect(self.toggle_receiver)
        row = QHBoxLayout()
        row.addWidget(QLabel('Syslog receiver'))
        row.addWidget(self.address, 1)
        row.addWidget(self.port)
        row.addWidget(self.start)
        layout.addLayout(row)
        self.status = QLabel('Device log stopped. Application events remain available.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.origin.currentTextChanged.connect(self.filter)
        self.severity.currentTextChanged.connect(self.filter)
        self.search.textChanged.connect(self.filter)
        self.pause.toggled.connect(lambda paused: self.redraw() if not paused else None)

    def appendPlainText(self, message):
        # Compatibility with the former application-only log.
        self.add({'source': 'Application', 'ip': '', 'severity': 'Info', 'message': message})

    def toPlainText(self):
        return '\n'.join(record['message'] for record in self.records)

    def add(self, record):
        record = dict(record, received=datetime.now().astimezone().isoformat(timespec='milliseconds'))
        self.records.append(record)
        self.records = self.records[-5000:]
        if self.archive.isChecked():
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                day = datetime.now().strftime('%Y-%m-%d')
                path = self.directory / f'events-{day}-{self.file_index:03d}.jsonl'
                while path.exists() and path.stat().st_size >= 10 * 1024 * 1024:
                    self.file_index += 1
                    path = self.directory / f'events-{day}-{self.file_index:03d}.jsonl'
                with path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            except OSError as exc:
                self.archive_error = f'Archive failed: {exc}. New events remain in memory only.'
                self.archive.setChecked(False)
                self.status.setText(self.archive_error)
        if not self.pause.isChecked():
            self.add_row(record)
            while self.tree.topLevelItemCount() > 5000:
                self.tree.takeTopLevelItem(0)
            if self.auto_scroll.isChecked():
                self.tree.scrollToBottom()

    def add_row(self, record):
        item = QTreeWidgetItem([record['received'], record['source'], record['ip'], record['severity'], record['message']])
        item.setData(0, Qt.UserRole, record)
        item.setToolTip(4, record['message'])
        self.tree.addTopLevelItem(item)
        item.setHidden(not self.matches(record))

    def matches(self, record):
        return ((self.origin.currentText() == 'All' or self.origin.currentText() == record['source'])
            and (self.severity.currentIndex() == 0 or self.severity.currentText() == record['severity'])
            and self.search.text().casefold() in (record['message'] + ' ' + record['ip']).casefold())

    def filter(self, *_):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setHidden(not self.matches(item.data(0, Qt.UserRole)))

    def redraw(self):
        self.tree.clear()
        for record in self.records:
            self.add_row(record)

    def toggle_receiver(self):
        if not getattr(self, 'permission_check', lambda _: True)('events'):
            return
        if self.socket.state() == QAbstractSocket.BoundState:
            self.stop_receiver()
        else:
            self.start_receiver(self.address.currentData(), self.port.value())

    def start_receiver(self, address, port):
        if not self.socket.bind(QHostAddress(address), port, QAbstractSocket.DontShareAddress):
            self.status.setText(f'Could not start device log: {self.socket.errorString()}')
            return False
        self.received = 0
        self.start.setText('Stop Device Log')
        index = self.address.findData(address)
        if index >= 0:
            self.address.setCurrentIndex(index)
        self.port.setValue(self.socket.localPort())
        self.address.setEnabled(False)
        self.port.setEnabled(False)
        self.status.setText(f'Listening on {address}:{self.socket.localPort()} · no device messages yet')
        return True

    def stop_receiver(self):
        self.socket.close()
        self.start.setText('Start Device Log')
        self.address.setEnabled(True)
        self.port.setEnabled(True)
        self.status.setText(f'Device log stopped · {self.received} messages received')

    def receive(self):
        from PySide6.QtCore import QTimer
        for _ in range(100):
            if not self.socket.hasPendingDatagrams():
                break
            datagram = self.socket.receiveDatagram(65535)
            record = parse_syslog(bytes(datagram.data()))
            record.update(source='Devices', ip=datagram.senderAddress().toString())
            self.add(record)
            self.received += 1
        self.status.setText(f'Device log listening · {self.received} messages received' +
                           (f' · {self.archive_error}' if self.archive_error else ''))
        if self.socket.hasPendingDatagrams():
            QTimer.singleShot(0, self.receive)

    def copy_selected(self):
        QApplication.clipboard().setText('\n'.join(json.dumps(item.data(0, Qt.UserRole), ensure_ascii=False)
            for item in self.tree.selectedItems()))

    def export_visible(self):
        if not getattr(self, 'permission_check', lambda _: True)('events'):
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export Visible Events', 'events.jsonl', 'Event archive (*.jsonl)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as stream:
                    for index in range(self.tree.topLevelItemCount()):
                        item = self.tree.topLevelItem(index)
                        if not item.isHidden():
                            stream.write(json.dumps(item.data(0, Qt.UserRole), ensure_ascii=False) + '\n')
            except OSError as exc:
                self.status.setText(f'Export failed: {exc}')

    def open_archive(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory.resolve()))):
                self.status.setText('Could not open archive folder.')
        except OSError as exc:
            self.status.setText(f'Could not open archive folder: {exc}')
