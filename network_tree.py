"""Compact grouped inventory navigation; groups are not device records."""
from localization import tr
import ipaddress
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QStyle

KIND = Qt.UserRole + 2
SORT = Qt.UserRole + 3
STATUS = Qt.UserRole + 5
SITE_GROUPS = {}


def device_family(device, site_groups=None):
    assigned = (SITE_GROUPS if site_groups is None else site_groups).get(device.get('ip'))
    if assigned:
        return assigned['group']
    kind = device.get('device_type', '').casefold()
    if kind == 'lwwd':
        return 'PC Audio Drivers'
    if kind.startswith('axiaxnode'):
        return 'xNodes'
    if kind == 'livemic':
        return 'Microphone Nodes'
    if kind == 'livert':
        return 'Router Selectors'
    if kind == 'liveio':
        return 'Audio Nodes'
    if kind in ('vx engine', 'vset'):
        return 'Telephony'
    if kind in ('qor', 'quasar', 'q.engine', 'qengine'):
        return 'Consoles & Engines'
    if kind.startswith('omnia'):
        return 'Audio Processors'
    return 'Other Devices' if kind else 'Awaiting Identification'


class OrderedItem(QTreeWidgetItem):
    def __lt__(self, other):
        return str(self.data(0, SORT) or self.text(0)) < str(other.data(0, SORT) or other.text(0))


class NetworkTree(QTreeWidget):
    def __init__(self, groups_path=None):
        super().__init__()
        self.site_groups = SITE_GROUPS
        self.groups_error = ''
        if groups_path is not None:
            self.site_groups = {}
            try:
                path = Path(groups_path)
                if path.exists():
                    groups = json.loads(path.read_text(encoding='utf-8'))
                    if not isinstance(groups, dict) or any(
                        not isinstance(v, dict) or not isinstance(v.get('group'), str)
                        for v in groups.values()):
                        raise ValueError('Invalid device group reference')
                    self.site_groups = groups
            except (ValueError, OSError) as exc:
                self.groups_error = str(exc)
        self.by_url = {}
        self.groups = {}
        self.grouped = True
        self.query = ''
        self.setHeaderLabels([tr('Device / Source'), tr('State')])
        self.setColumnWidth(0, 285)
        self.setMinimumWidth(380)
        self.setIndentation(16)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.sortItems(0, Qt.AscendingOrder)
        self.itemExpanded.connect(self.only_one_device_expanded)
        self.itemClicked.connect(self.select_device)

    def devices(self):
        return list(self.by_url.values())

    def ensure_device(self, url, device):
        item = self.by_url.get(url)
        if item is None:
            item = OrderedItem()
            item.setData(0, Qt.UserRole, url)
            item.setData(0, KIND, 'device')
            self.by_url[url] = item
        address = device['ip']
        numeric = int(ipaddress.ip_address(address))
        item.setData(0, SORT, f'{numeric:040d}')
        family = device_family(device, self.site_groups)
        item.setData(0, Qt.UserRole + 6, family)
        label = device.get('name') or ' '.join(filter(None, [device.get('product'), device.get('model')]))
        if not label:
            label = {'livemic': 'Microphone Node', 'lwwd': 'PC Audio Driver',
                     'livert': 'Router Selector'}.get(device.get('device_type', '').casefold(),
                     device.get('device_type') or 'Identifying…')
            if family == 'Telephony' and not device.get('device_type'):
                label = 'Telephony device'
        item.setText(0, f'{address} · {label}')
        icon = QStyle.SP_ComputerIcon if family == 'PC Audio Drivers' else QStyle.SP_DriveNetIcon
        item.setIcon(0, self.style().standardIcon(icon))
        self.place(item)
        return item

    def place(self, item):
        family = item.data(0, Qt.UserRole + 6)
        group = None
        if self.grouped:
            if family not in self.groups:
                group = OrderedItem([tr(family), ''])
                group.setData(0, KIND, 'group')
                group.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                self.addTopLevelItem(group)
                group.setExpanded(False)
                self.groups[family] = group
            group = self.groups[family]
        previous = item.parent()
        top_index = self.indexOfTopLevelItem(item)
        if previous is not group or (group is None and top_index < 0):
            if previous:
                previous.takeChild(previous.indexOfChild(item))
            elif top_index >= 0:
                self.takeTopLevelItem(top_index)
            group.addChild(item) if group else self.addTopLevelItem(item)
        for name, root in list(self.groups.items()):
            root.setText(1, str(root.childCount()))
            if root.childCount() == 0:
                self.takeTopLevelItem(self.indexOfTopLevelItem(root))
                del self.groups[name]

    def set_grouped(self, grouped):
        self.grouped = grouped
        for item in self.devices():
            self.place(item)
        self.filter(self.query)

    def set_observation(self, item, status):
        labels = {'Advertised · audio unverified': 'Seen', 'Details read · audio unverified': 'Read',
            'Saved · monitoring stopped': 'Saved', 'Saved · not verified': 'Saved',
            'Not yet observed': 'Waiting', 'Announcement timed out': 'Timed out'}
        item.setData(0, STATUS, status)
        item.setText(1, tr(labels.get(status, status)))
        item.setToolTip(1, tr(status) + '\n' + tr('Audio health is not verified.'))
        item.setForeground(1, QColor('#9a5600' if status == 'Announcement timed out' else '#4d5966'))

    def filter(self, query):
        self.query = query.strip().casefold()
        for item in self.devices():
            match = self.query in item.text(0).casefold()
            source_match = any(self.query in item.child(i).text(0).casefold() for i in range(item.childCount()))
            item.setHidden(not (match or source_match))
        for group in self.groups.values():
            group.setHidden(all(group.child(i).isHidden() for i in range(group.childCount())))
            if self.query and not group.isHidden():
                group.setExpanded(True)

    def only_one_device_expanded(self, selected):
        if selected.data(0, KIND) == 'device':
            for item in self.devices():
                if item is not selected:
                    item.setExpanded(False)

    def select_device(self, item, _):
        if item.data(0, KIND) == 'device':
            item.setExpanded(True)
