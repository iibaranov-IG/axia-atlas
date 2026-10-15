"""Workspace entry points backed by the existing equipment and scenario stores."""
from localization import tr
import ipaddress
from urllib.parse import urlsplit, urlunsplit
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QLabel, QInputDialog, QMessageBox, QTreeWidgetItem)
from equipment import EquipmentStore, is_network_card
from scenarios import ScenarioStore


def is_studio_card(card):
    """Studio/Axia records belong to Network; Devices is the external-equipment register."""
    identity = ' '.join(str(card.get(key, '')) for key in
                        ('ip', 'name', 'manufacturer', 'model', 'category')).casefold()
    return (str(card.get('ip', '')).startswith('asset:') or
            'axia' in identity or 'telos alliance' in identity or
            'livewire' in identity or 'studio microphone' in identity)


def management_url(value, fallback):
    """Return a browser URL from a saved management endpoint.

    Older equipment cards allowed ``IP:port``.  QUrl reads that form as a
    custom scheme, so make the intended HTTP scheme explicit before opening.
    """
    raw = str(value or '').strip()
    if not raw:
        host = '[' + fallback + ']' if ':' in fallback else fallback
        return f'http://{host}/'
    parsed = urlsplit(raw if '://' in raw else 'http://' + raw)
    if parsed.scheme.casefold() not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Management URL must use HTTP or HTTPS')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Invalid management port') from exc
    host = parsed.hostname
    if ':' in host and not host.startswith('['):
        host = '[' + host + ']'
    netloc = host + (f':{port}' if port is not None else '')
    return urlunsplit((parsed.scheme, netloc, parsed.path or '/', parsed.query, ''))


class DevicesNavigator(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.store = EquipmentStore(atlas.data_dir / 'state' / 'equipment.sqlite3')
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Find device, manufacturer, model or IP…'))
        layout.addWidget(self.search)
        self.items = QListWidget()
        layout.addWidget(self.items, 1)
        for title, callback in [('Add Device…', self.add), ('Open Card', self.open_card),
                                ('Open Configuration UI', self.open_ui), ('Refresh', self.refresh)]:
            button = QPushButton(tr(title))
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addWidget(QLabel(tr('External equipment register · saved on this workstation')))
        self.search.textChanged.connect(self.refresh)
        self.items.itemDoubleClicked.connect(self.open_card)
        self.refresh()

    def refresh(self):
        self.items.clear()
        if not self.atlas.access.allowed('equipment'): return
        query = self.search.text().casefold().strip()
        for card in self.store.cards():
            if is_studio_card(card):
                continue
            identifier = card['ip'] if is_network_card(card['ip']) else ''
            text = f'{card["name"] or card["ip"]}\n{card["manufacturer"]} {card["model"]}' + (f' · {identifier}' if identifier else '')
            if query and query not in (text + ' ' + card['category']).casefold(): continue
            item = QListWidgetItem(text.strip())
            item.setData(Qt.UserRole, card)
            self.items.addItem(item)

    def add(self):
        if not self.atlas.access.allowed('equipment'): return
        address, ok = QInputDialog.getText(self, tr('Add Device'), tr('Device IP address:'))
        if not ok: return
        raw = address.strip()
        parsed = urlsplit(raw if '://' in raw else '//' + raw)
        try: address = str(ipaddress.ip_address(parsed.hostname or raw))
        except ValueError:
            QMessageBox.warning(self, tr('Invalid address'), tr('Enter a valid IPv4 or IPv6 address.'))
            return
        panel = self.atlas.open_equipment(address)
        if parsed.scheme and parsed.hostname:
            panel.fields['management_url'].setText(raw)

    def open_card(self, *_):
        item = self.items.currentItem()
        if item: self.atlas.open_equipment(item.data(Qt.UserRole)['ip'])

    def open_ui(self):
        if not self.atlas.access.allowed('equipment') or not self.atlas.access.allowed('device_ui'): return
        item = self.items.currentItem()
        if not item: return
        card = item.data(Qt.UserRole)
        if not is_network_card(card['ip']):
            QMessageBox.information(self, tr('Open Configuration UI'), tr('Physical equipment does not have a network configuration page.'))
            return
        try:
            url = management_url(card.get('management_url', ''), card['ip'])
        except ValueError as exc:
            QMessageBox.warning(self, tr('Open Configuration UI'), str(exc))
            return
        device = QTreeWidgetItem([card['name'] or card['ip']])
        device.setData(0, Qt.UserRole, url)
        self.atlas.open_device(device)


class ScenariosNavigator(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.store = ScenarioStore(atlas.data_dir / 'state' / 'scenarios')
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        layout.addWidget(self.items, 1)
        for title, callback in [('New Scenario', self.new), ('Open Scenario', self.open), ('Refresh', self.refresh)]:
            button = QPushButton(tr(title))
            button.clicked.connect(callback)
            layout.addWidget(button)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.items.itemDoubleClicked.connect(self.open)
        self.refresh()

    def refresh(self):
        self.items.clear()
        if not self.atlas.access.allowed('scenarios'): return
        try:
            for plan in self.store.plans():
                item = QListWidgetItem(plan['name'])
                item.setData(Qt.UserRole, plan['id'])
                self.items.addItem(item)
            self.status.setText((tr('Open a scenario to review primary and backup assignments.') if self.items.count() else tr('No saved scenarios. Create a scenario to define primary and backup assignments.')))
        except (OSError, ValueError, KeyError) as exc:
            self.status.setText(str(exc))

    def new(self):
        panel = self.atlas.open_scenarios()
        if panel: panel.new()

    def open(self, *_):
        item = self.items.currentItem()
        if not item: return
        panel = self.atlas.open_scenarios()
        if not panel: return
        for index in range(panel.saved.count()):
            if panel.saved.itemData(index)['id'] == item.data(Qt.UserRole):
                panel.saved.setCurrentIndex(index)
                panel.load()
                break
