"""Axia Atlas desktop foundation. No implicit connections to broadcast devices."""
import ipaddress
import json
import sys
import urllib.request
import time
import copy
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QSettings, QThread, Signal, QUrl, Qt, QTimer
from PySide6.QtNetwork import QNetworkInterface, QAbstractSocket
from discovery import DiscoveryReceiver
from inventory import Inventory
from health import ChangeHistory, HealthPanel
from access_control import AccessStore, PERMISSIONS
from access_server import RemoteAccess
from administration import AdministrationDialog, SignInDialog, ERRORS
from document_viewer import DocumentViewer
from app_paths import application_data_dir, VERSION
from functools import wraps
from resources import ResourceLibrary, ResourceNavigator
from device_auth import authenticate
from audio_monitor import AudioSourceList, CompactPlayer
from recordings_panel import RecordingsPanel
from events import EventsPanel
from device_reader import DeviceReadJob
from network_tree import NetworkTree, OrderedItem, KIND, SORT, STATUS
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QDockWidget, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QComboBox, QFileDialog, QInputDialog,
    QMessageBox, QMenu, QTabBar, QSpinBox,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage


def requires(permission):
    def decorate(method):
        @wraps(method)
        def checked(self, *args, **kwargs):
            if not self.access.allowed(permission):
                self.statusBar().showMessage('Access denied: ' + PERMISSIONS[permission])
                return
            return method(self, *args, **kwargs)
        return checked
    return decorate


class SessionRefresh(QThread):
    refreshed = Signal(object)
    failed = Signal(str)

    def __init__(self, access):
        super().__init__()
        self.access = access
        self.token = access.token

    def run(self):
        try:
            self.refreshed.emit(self.access.call('/session')['user'])
        except Exception as exc:
            self.failed.emit(str(exc))


def device_url(value):
    """Manual inventory accepts IP literals, avoiding ambiguous URL interpretation."""
    address = ipaddress.ip_address(value.strip())
    host = f'[{address}]' if address.version == 6 else str(address)
    return f'http://{host}/'


class OllamaRequest(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, model=None, prompt=None):
        super().__init__()
        self.model, self.prompt = model, prompt

    def run(self):
        try:
            if self.model is None:
                request = urllib.request.Request('http://127.0.0.1:11434/api/tags')
            else:
                data = json.dumps({'model': self.model, 'stream': False, 'messages': [
                    {'role': 'system', 'content': 'You are a broadcast engineering advisor. '
                     'You have no device access. Distinguish facts from hypotheses. '
                     'Never claim to have inspected or changed equipment.'},
                    {'role': 'user', 'content': self.prompt},
                ]}).encode()
                request = urllib.request.Request('http://127.0.0.1:11434/api/chat',
                    data=data, headers={'Content-Type': 'application/json'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=60) as response:
                self.result.emit(json.load(response))
        except Exception as exc:
            self.failed.emit(str(exc))


class Atlas(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__()
        data_dir = Path(data_dir) if data_dir else application_data_dir()
        self.data_dir = data_dir
        self.settings = QSettings(str(data_dir / 'layout.ini'), QSettings.IniFormat)
        self.access_path = data_dir / 'state' / 'accounts.sqlite3'
        self.local_access = AccessStore(self.access_path)
        self.access = self.local_access
        if self.settings.value('account_server_url'):
            self.access = RemoteAccess(self.settings.value('account_server_url'), self.settings.value('account_server_fingerprint', ''))
        self.account_server = None
        self.session_poll = None
        self.permission_signature = None
        self.shutdown_done = False
        self.setWindowTitle(f'Axia Atlas — {VERSION}')
        self.resize(1440, 900)
        self.jobs = []
        self.discovery_active = False
        self.observed_times = {}
        self.inspect_queue = []
        self.inspect_jobs = {}
        self.inspected_this_scan = set()
        self.closing_requested = False
        self.inventory = Inventory(data_dir / 'state' / 'inventory.json')
        self.inventory_error = False
        self.changes = ChangeHistory(data_dir / 'state' / 'changes.jsonl')
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabs)
        self.log = EventsPanel(data_dir / 'state' / 'events')
        self.add_discovery_page()
        tasks_page = self.add_page('Tasks', 'Scheduled tasks are not available yet',
            'This page is reserved for a future job queue. It does not schedule or run operations.\n'
            'To record a channel now, use Record in the Audio panel.')
        self.tasks_audio = QPushButton('Open Audio Recording')
        self.tasks_audio.clicked.connect(self.open_audio)
        tasks_page.layout().insertWidget(2, self.tasks_audio, 0, Qt.AlignLeft)
        self.tabs.setTabToolTip(1, 'Future job queue. Manual audio recording is available in Audio.')
        self.tabs.addTab(self.log, 'Events')
        self.audio_details = QWidget()
        self.audio_details.setLayout(QVBoxLayout())
        self.tabs.addTab(self.audio_details, 'Audio Monitor')
        self.fixed_tabs = self.tabs.count()
        for index in range(self.fixed_tabs):
            self.tabs.tabBar().setTabButton(index, QTabBar.RightSide, None)
        self.network = NetworkTree()
        self.network.itemDoubleClicked.connect(lambda item, _: self.open_device(item))
        self.network.setContextMenuPolicy(Qt.CustomContextMenu)
        self.network.customContextMenuRequested.connect(self.device_menu)
        network_panel = QWidget()
        network_layout = QVBoxLayout(network_panel)
        network_layout.setContentsMargins(4, 4, 4, 4)
        self.network_search = QLineEdit()
        self.network_search.setPlaceholderText('Find device, IP or channel…')
        self.network_search.textChanged.connect(self.network.filter)
        network_layout.addWidget(self.network_search)
        self.grouping = QComboBox()
        self.grouping.addItems(['Group by device type', 'All devices by IP'])
        self.grouping.currentIndexChanged.connect(lambda index: self.network.set_grouped(index == 0))
        network_layout.addWidget(self.grouping)
        network_layout.addWidget(self.network)
        network_layout.addWidget(QLabel('Seen = announcement received · audio not tested'))
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(network_panel, 'Network')
        self.audio_sources = AudioSourceList(self.settings)
        self.left_tabs.addTab(self.audio_sources, 'Audio')
        self.library_nav = ResourceNavigator()
        self.library_nav.set_devices([])
        self.library_nav.selected.connect(self.open_resource)
        self.left_tabs.addTab(self.library_nav, 'Library')
        self.player = CompactPlayer(lambda: self.interface_objects.get(self.interfaces.currentData()), self.settings)
        self.player.permission_check = self.access_allowed
        self.player.logged.connect(self.record)
        self.player.failed.connect(lambda message: self.record(message, severity='Error'))
        self.audio_sources.selected.connect(self.player.select)
        self.audio_details.layout().addWidget(QLabel('Audio reception statistics'))
        audio_adapter = QPushButton('Select Audio Network Adapter…')
        audio_adapter.clicked.connect(self.select_audio_adapter)
        self.audio_details.layout().addWidget(audio_adapter)
        self.audio_details.layout().addWidget(self.player.detail_label)
        self.recordings = RecordingsPanel(self.settings)
        self.recordings.permission_check = self.access_allowed
        self.player.recording_finished.connect(self.recordings.add_file)
        self.recordings.playback_requested.connect(self.player.stop)
        self.player.monitoring_started.connect(self.recordings.media.stop)
        self.audio_details.layout().addWidget(self.recordings, 1)
        self.health = HealthPanel(self)
        self.tabs.addTab(self.health, 'Health')
        self.fixed_tabs = self.tabs.count()
        self.tabs.tabBar().setTabButton(self.fixed_tabs - 1, QTabBar.RightSide, None)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.left_tabs, 1)
        left_layout.addWidget(self.player)
        self.network_dock = self.dock('Workspace', 'network', left_panel, Qt.LeftDockWidgetArea)
        self.network.itemClicked.connect(lambda item, _: self.select_audio_item(item) if item.data(0, KIND) == 'source' else None)
        assistant = QWidget()
        layout = QVBoxLayout(assistant)
        self.connection = QLabel('Not connected · local Ollama')
        layout.addWidget(self.connection)
        self.connect_button = QPushButton('Connect to Ollama')
        self.connect_button.clicked.connect(self.connect_ollama)
        layout.addWidget(self.connect_button)
        self.models = QComboBox()
        layout.addWidget(self.models)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        layout.addWidget(self.chat)
        layout.addWidget(QLabel('Only your entered text is sent. Each question is independent.'))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText('Ask an engineering question…')
        self.prompt.setMaximumHeight(110)
        layout.addWidget(self.prompt)
        self.send = QPushButton('Send')
        self.send.setEnabled(False)
        self.send.clicked.connect(self.ask)
        layout.addWidget(self.send)
        self.assistant_dock = self.dock('Engineering Assistant', 'assistant', assistant, Qt.RightDockWidgetArea)
        self.make_menu()
        self.log.permission_check = self.access_allowed
        self.receiver = DiscoveryReceiver(self)
        self.receiver.observed.connect(self.device_observed)
        self.log.socket.stateChanged.connect(lambda _: self.update_status())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.discovery_tick)
        self.timer.start(1000)
        if self.settings.value('geometry'):
            self.restoreGeometry(self.settings.value('geometry'))
            self.restoreState(self.settings.value('layout'))
        self.record('Application started. No automatic device connections.')
        try:
            self.inventory.load()
            for device in self.inventory.devices.values():
                self.render_device(device, 'Saved · not verified')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.inventory_error = True
            self.record(f'Inventory could not be loaded; original file preserved: {exc}')
        self.discovery_tick()
        self.account_timer = QTimer(self)
        self.account_timer.timeout.connect(self.refresh_session)
        self.account_timer.start(5000)
        self.apply_permissions()
        if self.access.configured:
            QTimer.singleShot(0, self.sign_in)

    def access_allowed(self, permission):
        return self.access.allowed(permission)

    def open_administration(self):
        dialog = AdministrationDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def sign_in(self):
        if self.access.user or not self.access.configured:
            return
        dialog = SignInDialog(self.access, self)
        dialog.exec()
        dialog.deleteLater()
        self.apply_permissions()

    def refresh_session(self):
        if isinstance(self.access, RemoteAccess) and self.access.token and self.session_poll is None:
            job = SessionRefresh(self.access)
            self.session_poll = job
            job.refreshed.connect(lambda user: self.session_result(job, user))
            job.failed.connect(lambda error: self.session_result(job, None, error))
            job.finished.connect(lambda: self.session_poll_finished(job))
            job.start()
        elif not isinstance(self.access, RemoteAccess):
            self.apply_permissions()

    def session_poll_finished(self, job):
        if self.session_poll is job:
            self.session_poll = None
        job.deleteLater()

    def session_result(self, job, user, error=''):
        if job.access is not self.access or job.token != self.access.token:
            return
        self.access._user = user
        if user is None:
            self.access.token = ''
            self.record('Account session ended: ' + error, severity='Warning')
        self.apply_permissions()

    def end_session(self):
        if self.inspect_jobs or self.jobs:
            QMessageBox.information(self, 'Work in progress', 'Wait for current device reads or assistant requests to finish before signing out.')
            return False
        self.player.stop()
        self.recordings.media.stop()
        self.receiver.stop()
        self.discovery_active = False
        self.inspect_queue.clear()
        self.log.stop_receiver()
        self.close_private_tabs()
        self.chat.clear()
        self.prompt.clear()
        try:
            if self.access.user or isinstance(self.access, RemoteAccess):
                self.access.logout()
        except ERRORS:
            pass  # Remote logout always discards the local token even offline.
        self.apply_permissions()
        return True

    def sign_out(self):
        if self.end_session():
            self.sign_in()

    def close_private_tabs(self):
        for index in range(self.tabs.count() - 1, self.fixed_tabs - 1, -1):
            self.close_tab(index)

    def apply_permissions(self):
        allowed = {key: self.access.allowed(key) for key in PERMISSIONS}
        user = self.access.user
        signature = (user['id'] if user else None, tuple(allowed.values()), self.access.configured)
        self.session_action.setText(('Account: ' + user['name']) if user else
            'Account: Sign In' if self.access.configured else 'Administration · Set Up Accounts')
        self.logout_action.setEnabled(user is not None)
        if signature == self.permission_signature:
            return
        self.permission_signature = signature
        if not allowed['audio']:
            self.player.stop()
            self.recordings.media.stop()
        elif not allowed['record']:
            self.player.stop_recording('Recording permission revoked')
        if not allowed['network']:
            self.receiver.stop()
            self.discovery_active = False
            self.inspect_queue.clear()
        if not allowed['events']:
            self.log.stop_receiver()
        if not allowed['device_ui'] or not allowed['library']:
            for index in range(self.tabs.count() - 1, self.fixed_tabs - 1, -1):
                page = self.tabs.widget(index)
                if isinstance(page, QWebEngineView) and not allowed['device_ui'] or isinstance(page, (ResourceLibrary, DocumentViewer)) and not allowed['library']:
                    self.close_tab(index)
        if not allowed['downloads']:
            for index in range(self.fixed_tabs, self.tabs.count()):
                page = self.tabs.widget(index)
                if isinstance(page, ResourceLibrary):
                    page.download.cancel()
                    page.download_button.setEnabled(False)
        for index, permission in [(0, 'network'), (1, 'audio'), (2, 'library')]:
            self.left_tabs.setTabEnabled(index, allowed[permission])
            self.left_tabs.widget(index).setEnabled(allowed[permission])
        for page, permission in [(self.tabs.widget(0), 'network'), (self.tabs.widget(1), 'audio'),
                                 (self.log, 'events'), (self.audio_details, 'audio'), (self.health, 'diagnostics')]:
            self.tabs.setTabEnabled(self.tabs.indexOf(page), allowed[permission])
            page.setEnabled(allowed[permission])
            page.setVisible(allowed[permission] and self.tabs.currentWidget() is page)
        self.player.setEnabled(allowed['audio'])
        self.player.record_button.setEnabled(allowed['audio'] and allowed['record'] and bool(self.player.source))
        self.assistant_dock.widget().setEnabled(allowed['ollama'])
        if not allowed['ollama']:
            self.chat.clear()
            self.prompt.clear()
        self.network.setVisible(allowed['network'])
        self.tabs.setVisible(any(allowed.values()))
        self.network_dock.widget().setVisible(allowed['network'] or allowed['audio'] or allowed['library'])
        self.assistant_dock.widget().setVisible(allowed['ollama'])

    def add_discovery_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel('Discover the Livewire network')
        heading.setStyleSheet('font-size: 22px; font-weight: 600; margin: 16px;')
        layout.addWidget(heading)
        description = QLabel('Select the broadcast network adapter, then start listening.\n'
            'The scanner listens for announcements and reads device details. Audio health remains unverified.')
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.interfaces = QComboBox()
        self.interfaces.setPlaceholderText('Select the broadcast network adapter…')
        self.interfaces.setMinimumWidth(300)
        self.reload_interfaces()
        row.addWidget(QLabel('Network adapter'))
        row.addWidget(self.interfaces, 1)
        self.refresh_interfaces = QPushButton('Refresh Adapters')
        self.refresh_interfaces.clicked.connect(self.reload_interfaces)
        row.addWidget(self.refresh_interfaces)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Announcement timeout (seconds)'))
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setValue(int(self.settings.value('discovery_timeout', 160)))
        row.addWidget(self.timeout)
        row.addStretch()
        self.discovery_button = QPushButton('Start Network Scan')
        self.discovery_button.clicked.connect(self.toggle_discovery)
        row.addWidget(self.discovery_button)
        layout.addLayout(row)
        self.discovery_status = QLabel('Stopped')
        layout.addWidget(self.discovery_status)
        row = QHBoxLayout()
        self.find_address = QLineEdit()
        self.find_address.setPlaceholderText('Find a specific device by IP address…')
        self.find_address.returnPressed.connect(self.find_device)
        row.addWidget(self.find_address, 1)
        find_button = QPushButton('Find Device')
        find_button.clicked.connect(self.find_device)
        row.addWidget(find_button)
        layout.addLayout(row)
        self.find_status = QLabel('Enter an address to read a specific device.')
        self.find_status.setWordWrap(True)
        layout.addWidget(self.find_status)
        layout.addWidget(QLabel('Previously discovered devices are retained. Expand a device to see advertised sources.'))
        layout.addStretch()
        self.tabs.addTab(page, 'Tools')

    def reload_interfaces(self):
        self.interfaces.clear()
        self.interface_objects = {}
        for interface in QNetworkInterface.allInterfaces():
            if not interface.flags() & QNetworkInterface.IsUp or interface.flags() & QNetworkInterface.IsLoopBack:
                continue
            addresses = [entry.ip().toString() for entry in interface.addressEntries()
                         if entry.ip().protocol() == QAbstractSocket.IPv4Protocol]
            if not addresses:
                continue
            self.interfaces.addItem(f'{interface.humanReadableName()} · {", ".join(addresses)}', interface.index())
            self.interface_objects[interface.index()] = interface
        saved = self.settings.value('discovery_interface', '')
        self.interfaces.setCurrentIndex(-1)
        for index in range(self.interfaces.count()):
            interface = self.interface_objects[self.interfaces.itemData(index)]
            if interface.name() == saved:
                self.interfaces.setCurrentIndex(index)

    @requires('network')
    def toggle_discovery(self):
        if self.discovery_active:
            self.receiver.stop()
            self.discovery_active = False
            self.observed_times.clear()
            self.inspect_queue.clear()
            self.record('Discovery stopped. Device availability is no longer being observed.')
        else:
            interface = self.interface_objects.get(self.interfaces.currentData())
            if interface is None:
                QMessageBox.warning(self, 'No network adapter', 'Select an available IPv4 network adapter.')
                return
            try:
                self.receiver.start(interface)
            except OSError as exc:
                self.record(f'Discovery could not start: {exc}')
                QMessageBox.warning(self, 'Discovery could not start', str(exc))
                return
            self.discovery_active = True
            self.observed_times.clear()
            self.inspected_this_scan.clear()
            self.settings.setValue('discovery_interface', interface.name())
            self.record(f'Discovery listening on {self.interfaces.currentText()}. Receive-only announcements.')
        self.interfaces.setEnabled(not self.discovery_active)
        self.refresh_interfaces.setEnabled(not self.discovery_active)
        self.discovery_button.setText('Stop Network Scan' if self.discovery_active else 'Start Network Scan')
        self.discovery_tick()

    def device_observed(self, event):
        before = copy.deepcopy(self.inventory.devices.get(event['ip'], {}))
        new = event['ip'] not in self.inventory.devices
        previous_revision = self.inventory.devices.get(event['ip'], {}).get('version')
        if previous_revision is not None and previous_revision != event['version']:
            self.inspected_this_scan.discard(event['ip'])
        device = self.inventory.observe(event, datetime.now().astimezone().isoformat(timespec='seconds'))
        self.track_changes(event['ip'], before, device, 'Livewire announcement')
        self.observed_times[event['ip']] = time.monotonic()
        self.render_device(device, 'Advertised · audio unverified')
        if new:
            self.record(f'Device discovered: {event["ip"]} {event["name"]}')
        if event['ip'] not in self.inspected_this_scan and self.discovery_active:
            self.inspected_this_scan.add(event['ip'])
            self.queue_inspection(event['ip'])

    @requires('network')
    def find_device(self):
        try:
            address = str(ipaddress.IPv4Address(self.find_address.text().strip()))
        except ValueError:
            QMessageBox.warning(self, 'Invalid address', 'Enter the IPv4 address of the device.')
            return
        self.find_status.setText(f'Reading {address}…')
        self.queue_inspection(address)

    @requires('network')
    def queue_inspection(self, address):
        if self.closing_requested or address in self.inspect_jobs or address in self.inspect_queue:
            return
        if len(self.inspect_queue) >= 512:
            self.record('Device detail queue is full. Use Refresh Device Information for remaining devices.')
            return
        self.inspect_queue.append(address)
        self.record(f'Device information queued: {address}')
        self.start_inspections()

    def start_inspections(self):
        while self.inspect_queue and len(self.inspect_jobs) < 2 and not self.closing_requested:
            address = self.inspect_queue.pop(0)
            source = None
            interface = self.interface_objects.get(self.interfaces.currentData())
            if interface:
                for entry in interface.addressEntries():
                    if entry.ip().protocol() == QAbstractSocket.IPv4Protocol:
                        subnet = ipaddress.ip_network(f'{entry.ip().toString()}/{entry.prefixLength()}', strict=False)
                        if ipaddress.ip_address(address) in subnet:
                            source = entry.ip().toString()
                            break
            job = DeviceReadJob(address, source, self)
            self.inspect_jobs[address] = job
            job.completed.connect(self.device_inspected)
            job.failed.connect(self.inspection_failed)
            job.finished.connect(lambda a=address: self.inspection_finished(a))
            job.start()

    def device_inspected(self, address, result):
        before = copy.deepcopy(self.inventory.devices.get(address, {}))
        device = self.inventory.inspected(address, result, datetime.now().astimezone().isoformat(timespec='seconds'))
        self.track_changes(address, before, device, 'Device configuration read')
        self.render_device(device, 'Details read · audio unverified')
        if self.find_address.text().strip() == address:
            self.find_status.setText(f'Found {address} · {result["device_type"]} · software {result["firmware"]}'
                f' · {len(result["inspection_sources"])} source settings read')
            for item in self.network.devices():
                if QUrl(item.data(0, Qt.UserRole)).host() == address:
                    if item.parent():
                        item.parent().setExpanded(True)
                    item.setExpanded(True)
                    self.network.setCurrentItem(item)
                    self.network.scrollToItem(item)
                    break
        self.record(f'Device information read: {address} · {result["device_type"]} · '
            f'version {result["firmware"]} · {len(result["inspection_sources"])} sources'
            + ('' if result['inspection_complete'] else ' · source list incomplete'))
        self.save_inventory()

    def inspection_failed(self, address, message):
        if self.find_address.text().strip() == address:
            self.find_status.setText(f'Could not read {address}: {message}. See Events for details.')
        self.record(f'Device information unavailable: {address} · {message}', severity='Warning', ip=address)
        if address in self.inventory.devices:
            self.inventory.devices[address]['inspection_error'] = message
            self.inventory.dirty = True

    def inspection_finished(self, address):
        job = self.inspect_jobs.pop(address)
        job.deleteLater()
        self.start_inspections()
        if self.closing_requested and not self.inspect_jobs:
            self.close()

    def render_device(self, device, status):
        self.audio_sources.update_device(device)
        self.update_library_inventory()
        url = device_url(device['ip'])
        item = self.network.ensure_device(url, device)
        self.network.set_observation(item, status)
        item.setToolTip(0, f'Last announcement: {device.get("last_seen", "Unknown")}\n'
            f'Advertised source count: {device.get("source_count", "Unknown")}\n'
            f'Source details received: {device.get("sources_seen", "Not received")}\n'
            f'Device type: {device.get("device_type", "Unknown")}\n'
            f'Reported version: {device.get("firmware", "Unknown")} ({device.get("version_field", "")})\n'
            f'Details read: {device.get("inspection_at", "Not read")}\n'
            f'Source list: {"Complete" if device.get("inspection_complete") else "Partial or not read"}\n'
            f'Detail error: {device.get("inspection_error", "None")}\n'
            'Provenance: Livewire announcements and LWRP status queries. Audio health is not verified.')
        inspected = bool(device.get('inspection_complete') or device.get('inspection_sources'))
        sources = device.get('inspection_sources', []) if inspected else device.get('sources', [])
        signature = json.dumps([sources, inspected, device.get('inspection_stale'), device.get('device_type')], sort_keys=True)
        if item.data(0, Qt.UserRole + 4) == signature:
            self.network.filter(self.network_search.text())
            return
        item.setData(0, Qt.UserRole + 4, signature)
        item.takeChildren()
        if inspected and not sources and device.get('device_type', '').casefold() == 'quasar':
            child = OrderedItem(['Control surface · no published audio sources', 'NSRC: 0'])
            child.setData(0, KIND, 'info')
            child.setData(0, Qt.UserRole + 1, 'inspection')
            child.setToolTip(0, 'The surface reports zero Livewire sources. Audio streams are published by the audio engine.\n'
                'An associated engine has not been confirmed by Atlas; engine channels are not attributed to this surface automatically.')
            item.addChild(child)
        for source in sources:
            child = OrderedItem([f'{source["channel"] if source["channel"] is not None else "—"} · {source["name"] or "Unnamed source"}',
                ('Enabled' if source.get('enabled') is True else
                 'Disabled' if source.get('enabled') is False else 'State unknown') if inspected else
                ('Announced' if device.get('sources_current') and device['ip'] in self.observed_times else 'Saved')])
            child.setData(0, KIND, 'source')
            child.setData(0, Qt.UserRole + 7, dict(source, ip=device['ip']))
            child.setData(0, SORT, f'{source["slot"]:06d}')
            child.setData(0, Qt.UserRole + 1, 'inspection' if inspected else 'announcement')
            if inspected and device.get('inspection_stale'):
                child.setText(1, 'Changed')
            child.setToolTip(0, f'{source["multicast"]}\nSource slot: {source["slot"]}\n'
                f'Observed at: {device.get("inspection_at") if inspected else device.get("sources_seen", "Unknown")}\n'
                'Enabled is a configuration setting, not confirmation of audio. Select a channel to listen or record.')
            item.addChild(child)
        self.network.filter(self.network_search.text())

    def discovery_tick(self):
        now = time.monotonic()
        for item in self.network.devices():
            url = QUrl(item.data(0, Qt.UserRole))
            address = url.host()
            if address not in self.inventory.devices:
                continue
            last = self.observed_times.get(address)
            if not self.discovery_active:
                status = 'Saved · monitoring stopped'
            elif last is None:
                status = 'Not yet observed'
            elif now - last > self.timeout.value():
                status = 'Announcement timed out'
            else:
                status = 'Advertised · audio unverified'
            if item.data(0, STATUS) != status:
                try:
                    self.changes.add(address, 'Observation status', item.data(0, STATUS), status, 'Local discovery observer')
                except OSError as exc:
                    self.record(f'Change history could not be saved: {exc}', severity='Error')
                if status == 'Announcement timed out':
                    self.record(f'Announcement timeout: {address}. Device retained; audio health unknown.')
                self.network.set_observation(item, status)
            for child_index in range(item.childCount()):
                if item.child(child_index).data(0, Qt.UserRole + 1) == 'inspection':
                    continue
                item.child(child_index).setText(1, 'Announced' if status == 'Advertised · audio unverified'
                    and self.inventory.devices[address].get('sources_current') else 'Saved')
        state = 'Listening' if self.discovery_active else 'Stopped'
        self.discovery_status.setText(f'{state} · received {self.receiver.received} · other messages {self.receiver.ignored} · invalid {self.receiver.rejected}'
            f' · reading {len(self.inspect_jobs)} · queued {len(self.inspect_queue)}')
        self.update_status()
        self.save_inventory()
        self.health.refresh()

    def track_changes(self, address, before, after, origin):
        try:
            self.changes.compare(address, before, after, origin)
        except OSError as exc:
            self.record(f'Change history could not be saved: {exc}', severity='Error')

    def update_status(self):
        state = 'Listening' if self.discovery_active else 'Stopped'
        self.statusBar().showMessage(f'Discovery: {state} | {len(self.network.devices())} devices | '
            f'Device log: {"Listening" if self.log.socket.state() == QAbstractSocket.BoundState else "Stopped"}')

    def save_inventory(self):
        if self.inventory_error:
            return
        try:
            self.inventory.save()
        except OSError as exc:
            self.inventory_error = True
            self.record(f'Inventory save failed: {exc}. New observations remain in memory only.', severity='Error')

    def dock(self, title, name, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def add_page(self, name, title, text):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title)
        heading.setStyleSheet('font-size: 22px; font-weight: 600; margin: 16px;')
        layout.addWidget(heading)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()
        self.tabs.addTab(page, name)
        return page

    def action(self, menu, text, slot, shortcut=None):
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def make_menu(self):
        file = self.menuBar().addMenu('&File')
        add = self.action(file, 'Add Device…', self.add_device, 'Ctrl+N')
        self.action(file, 'Export Visible Events…', self.export_log, 'Ctrl+Shift+S')
        file.addSeparator()
        self.action(file, 'Exit', self.close, 'Alt+F4')
        edit = self.menuBar().addMenu('&Edit')
        self.action(edit, 'Copy', lambda: self.focus_edit('copy'), QKeySequence.Copy)
        self.action(edit, 'Select All', lambda: self.focus_edit('selectAll'), QKeySequence.SelectAll)
        view = self.menuBar().addMenu('&View')
        view.addAction(self.network_dock.toggleViewAction())
        view.addAction(self.assistant_dock.toggleViewAction())
        self.action(view, 'Restore Panel Layout', self.reset_layout)
        tools = self.menuBar().addMenu('&Tools')
        discover = self.action(tools, 'Network Discovery', lambda: self.tabs.setCurrentIndex(0), 'Ctrl+D')
        library = self.action(tools, 'Documentation && Firmware', self.open_library)
        self.action(tools, 'Audio Monitor', self.open_audio)
        self.action(tools, 'Events', lambda: self.tabs.setCurrentIndex(2))
        account = self.menuBar().addMenu('&Account')
        self.session_action = self.action(account, 'Administration', self.open_administration)
        self.action(account, 'Sign In', self.sign_in)
        self.logout_action = self.action(account, 'Sign Out / Switch User', self.sign_out)
        help_menu = self.menuBar().addMenu('&Help')
        self.action(help_menu, 'About Axia Atlas', lambda: QMessageBox.information(self,
            'Axia Atlas', f'{VERSION}\nIndependent broadcast engineering software.\nNot affiliated with or endorsed by Telos Alliance.\nPreview: validate before operational use.'))
        self.action(help_menu, 'Equipment Manuals', self.open_library)
        toolbar = self.addToolBar('Navigation')
        toolbar.setObjectName('navigation')
        self.nav = []
        for label, method in [('← Back', 'back'), ('→ Forward', 'forward'), ('⌂ Home', 'home'), ('↻ Refresh', 'reload')]:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, m=method: self.navigate(m))
            toolbar.addAction(action)
            self.nav.append(action)
        toolbar.addSeparator()
        toolbar.addAction(add)
        self.tabs.currentChanged.connect(self.update_nav)
        self.update_nav()

    def focus_edit(self, method):
        widget = QApplication.focusWidget()
        if hasattr(widget, method):
            getattr(widget, method)()

    @requires('library')
    def open_library(self):
        self.left_tabs.setCurrentIndex(2)
        self.network_dock.show()
        self.update_library_inventory()

    def update_library_inventory(self):
        devices = list(self.inventory.devices.values())
        self.library_nav.set_devices(devices)
        for index in range(self.fixed_tabs, self.tabs.count()):
            page = self.tabs.widget(index)
            if isinstance(page, ResourceLibrary):
                page.set_devices(devices)

    @requires('library')
    def open_document(self, url, title):
        for index in range(self.fixed_tabs, self.tabs.count()):
            page = self.tabs.widget(index)
            if isinstance(page, DocumentViewer) and page.property('document_url') == url.toString():
                self.tabs.setCurrentIndex(index)
                return
        page = DocumentViewer(self)
        self.tabs.setCurrentIndex(self.tabs.addTab(page, title))
        page.open(url)

    @requires('audio')
    def open_audio(self):
        self.left_tabs.setCurrentIndex(1)
        self.network_dock.show()
        self.tabs.setCurrentIndex(3)

    @requires('audio')
    def select_audio_adapter(self):
        if self.player.receiver or self.discovery_active:
            QMessageBox.information(self, 'Audio Network Adapter', 'Stop playback and network scanning before changing the adapter.')
            return
        choices = [self.interfaces.itemText(index) for index in range(self.interfaces.count())]
        if not choices:
            QMessageBox.information(self, 'Audio Network Adapter', 'No available network adapter was found.')
            return
        selected, ok = QInputDialog.getItem(self, 'Audio Network Adapter', 'Broadcast network adapter:', choices,
                                           max(0, self.interfaces.currentIndex()), False)
        if ok:
            self.interfaces.setCurrentIndex(choices.index(selected))
            self.settings.setValue('discovery_interface', self.interfaces.currentData())

    @requires('audio')
    def select_audio_item(self, item):
        source = item.data(0, Qt.UserRole + 7)
        if source:
            self.left_tabs.setCurrentIndex(1)
            self.audio_sources.select_source(source)

    @requires('library')
    def open_resource(self, entry):
        page = None
        for index in range(self.tabs.count()):
            if isinstance(self.tabs.widget(index), ResourceLibrary):
                self.tabs.setCurrentIndex(index)
                page = self.tabs.widget(index)
                break
        if page is None:
            page = ResourceLibrary()
            page.permission_check = self.access_allowed
            page.set_devices(list(self.inventory.devices.values()))
            page.open_requested.connect(self.open_document)
            self.tabs.setCurrentIndex(self.tabs.addTab(page, 'Documentation && Firmware'))
        page.search.clear()
        page.kind.setCurrentText(entry['kind'])
        page.family.setCurrentText(entry['family'])
        for index in range(page.table.topLevelItemCount()):
            item = page.table.topLevelItem(index)
            if item.data(0, Qt.UserRole) == entry:
                page.table.setCurrentItem(item)
                page.table.scrollToItem(item)
                break

    def update_nav(self, *_):
        browser = self.tabs.currentWidget()
        valid = isinstance(browser, QWebEngineView)
        for index, action in enumerate(self.nav):
            enabled = valid
            if valid and index < 2:
                enabled = browser.history().canGoBack() if index == 0 else browser.history().canGoForward()
            action.setEnabled(enabled)

    @requires('device_ui')
    def navigate(self, method):
        browser = self.tabs.currentWidget()
        if isinstance(browser, QWebEngineView):
            browser.setProperty('auth_cancelled', False)
            browser.setUrl(QUrl(browser.property('home'))) if method == 'home' else getattr(browser, method)()

    @requires('network')
    def add_device(self):
        value, ok = QInputDialog.getText(self, 'Add Device', 'Device IP address:')
        if not ok:
            return
        try:
            url = device_url(value)
        except ValueError:
            QMessageBox.warning(self, 'Invalid address', 'Enter a valid IPv4 or IPv6 address.')
            return
        if url in self.network.by_url:
            self.network.setCurrentItem(self.network.by_url[url])
            return
        item = self.network.ensure_device(url, {'ip': value.strip(), 'name': 'Manual device'})
        self.network.set_observation(item, 'Unknown')
        self.record(f'Manual inventory entry added: {value.strip()}. Health not verified.')
        self.statusBar().showMessage(f'{len(self.network.devices())} devices | Health unknown | See Events for device log status')

    def device_menu(self, position):
        item = self.network.itemAt(position)
        if item is None:
            return
        if item.data(0, KIND) in ('group', 'info'):
            return
        if item.data(0, KIND) == 'source':
            self.select_audio_item(item)
            return
        self.network.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction('Open Configuration UI', lambda: self.open_device(item))
        menu.addAction('Refresh Device Information', lambda: self.queue_inspection(QUrl(item.data(0, Qt.UserRole)).host()))
        menu.addAction('Documentation && Firmware…', self.open_library)
        menu.addAction('Copy IP Address', lambda: QApplication.clipboard().setText(QUrl(item.data(0, Qt.UserRole)).host()))
        menu.exec(self.network.viewport().mapToGlobal(position))

    @requires('device_ui')
    def open_device(self, item):
        if item.data(0, KIND) in ('group', 'info'):
            return
        if item.data(0, KIND) == 'source':
            self.select_audio_item(item)
            return
        url = item.data(0, Qt.UserRole)
        for index in range(self.fixed_tabs, self.tabs.count()):
            if self.tabs.widget(index).property('home') == url:
                self.tabs.setCurrentIndex(index)
                return
        browser = QWebEngineView()
        profile = QWebEngineProfile(browser)
        browser.setPage(QWebEnginePage(profile, browser))
        browser._atlas_profile = profile
        browser._atlas_access = lambda: self.access
        browser.page().authenticationRequired.connect(lambda url, auth: authenticate(browser, url, auth))
        browser.setProperty('home', url)
        browser.loadFinished.connect(lambda ok: self.record(
            f'Web page {item.text(0)}: {"loaded" if ok else "failed to load"}; audio health not assessed.'))
        browser.loadFinished.connect(self.update_nav)
        browser.urlChanged.connect(self.update_nav)
        self.tabs.setCurrentIndex(self.tabs.addTab(browser, item.text(0)))
        browser.setUrl(QUrl(url))

    def close_tab(self, index):
        if index >= self.fixed_tabs:
            widget = self.tabs.widget(index)
            if isinstance(widget, ResourceLibrary):
                widget.download.cancel()
            if isinstance(widget, DocumentViewer):
                widget.dispose()
            if isinstance(widget, QWebEngineView):
                widget.stop()
                page = widget.page()
                profile = widget._atlas_profile
                page.destroyed.connect(profile.deleteLater)
                profile.setParent(self)
                page.deleteLater()
            self.tabs.removeTab(index)
            widget.deleteLater()

    def record(self, message, severity='Info', ip=''):
        user = self.access.user
        self.log.add({'source': 'Application', 'ip': ip, 'severity': severity, 'message': message,
                      'atlas_user': user['name'] if user else 'Setup' if not self.access.configured else 'Signed out'})

    @requires('events')
    def export_log(self):
        self.tabs.setCurrentWidget(self.log)
        self.log.export_visible()

    def reset_layout(self):
        for dock, area in [(self.network_dock, Qt.LeftDockWidgetArea), (self.assistant_dock, Qt.RightDockWidgetArea)]:
            dock.setFloating(False)
            self.addDockWidget(area, dock)
            dock.show()

    def launch_request(self, job, success):
        self.jobs.append(job)
        self.connect_button.setEnabled(False)
        self.send.setEnabled(False)
        job.result.connect(success)
        job.failed.connect(lambda text: self.chat.appendPlainText('Connection/request failed: ' + text))
        job.finished.connect(lambda: self.request_finished(job))
        job.start()

    def request_finished(self, job):
        self.jobs.remove(job)
        self.connect_button.setEnabled(True)
        self.send.setEnabled(self.models.count() > 0)
        job.deleteLater()

    @requires('ollama')
    def connect_ollama(self):
        self.models.clear()
        self.connection.setText('Connecting to local Ollama…')
        job = OllamaRequest()
        job.failed.connect(lambda _: self.connection.setText('Ollama unavailable'))
        self.launch_request(job, self.models_received)

    def models_received(self, response):
        self.models.addItems([model['name'] for model in response.get('models', [])])
        self.connection.setText('Connected · local Ollama' if self.models.count() else 'Connected · no installed models')

    @requires('ollama')
    def ask(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt or not self.models.currentText():
            return
        self.chat.appendPlainText('You: ' + prompt)
        self.prompt.clear()
        self.launch_request(OllamaRequest(self.models.currentText(), prompt),
            lambda result: self.chat.appendPlainText('Assistant: ' + result.get('message', {}).get('content', 'No response text.')))

    def closeEvent(self, event):
        if self.shutdown_done:
            event.accept()
            return
        for index in range(self.fixed_tabs, self.tabs.count()):
            page = self.tabs.widget(index)
            if isinstance(page, ResourceLibrary):
                page.download.cancel()
        self.recordings.media.stop()
        self.player.stop()
        self.log.stop_receiver()
        if self.jobs:
            QMessageBox.information(self, 'Request in progress', 'Wait for the Ollama request to finish before closing.')
            event.ignore()
            return
        if self.inspect_jobs:
            self.closing_requested = True
            self.receiver.stop()
            self.discovery_active = False
            self.inspect_queue.clear()
            for job in self.inspect_jobs.values():
                job.requestInterruption()
            self.statusBar().showMessage('Finishing device reads before closing…')
            event.ignore()
            return
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('layout', self.saveState())
        self.settings.setValue('discovery_timeout', self.timeout.value())
        self.receiver.stop()
        self.save_inventory()
        self.account_timer.stop()
        if self.session_poll:
            self.session_poll.wait(4000)
        self.close_private_tabs()
        if self.account_server:
            self.account_server.stop()
            self.account_server = None
        self.timer.stop()
        self.local_access.db.close()
        self.shutdown_done = True
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from release_smoke import run
        sys.exit(run(app, Path(sys.argv[2])))
    window = Atlas()
    window.show()
    if not window.access.configured:
        QTimer.singleShot(0, window.open_administration)
    sys.exit(app.exec())
