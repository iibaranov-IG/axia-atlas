"""Operator-maintained equipment cards, separate from raw discovery evidence."""
from localization import tr
import ipaddress
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
    QLineEdit, QPlainTextEdit, QPushButton, QLabel, QMessageBox)


LEGACY_FIELDS = ('studio', 'rack', 'purpose', 'responsible', 'contact', 'notes')
FIELDS = ('name', 'manufacturer', 'model', 'category', 'management_url', 'asset_number', 'livewire_channel') + LEGACY_FIELDS

FIELD_LABELS = {
    'asset_number': 'Asset number',
    'livewire_channel': 'Livewire channel',
    'management_url': 'Management URL',
}


def card_key(value):
    """Return a stable card key without pretending a physical asset has an IP."""
    value = str(value).strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if re.fullmatch(r'asset:[a-z0-9][a-z0-9._-]{0,100}', value):
            return value
    raise ValueError('Enter a valid IPv4 or IPv6 address, or a physical asset identifier.')


def is_network_card(value):
    try:
        ipaddress.ip_address(str(value))
        return True
    except ValueError:
        return False


def card_sort_key(value):
    try:
        return (0, int(ipaddress.ip_address(value)))
    except ValueError:
        return (1, str(value))


class EquipmentStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cards (ip TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, ip TEXT NOT NULL, body TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, address):
        address = card_key(address)
        with self.connection() as db:
            row = db.execute('SELECT revision,body FROM cards WHERE ip=?', (address,)).fetchone()
        return dict.fromkeys(FIELDS, '') | (dict(json.loads(row[1]), revision=row[0]) if row else {'revision': 0})

    def cards(self):
        with self.connection() as db:
            return [dict.fromkeys(FIELDS, '') | json.loads(body) | {'ip': ip, 'revision': revision}
                    for ip, revision, body in db.execute('SELECT ip,revision,body FROM cards ORDER BY ip')]

    def save(self, address, values, revision, actor):
        address = card_key(address)
        if not set(values).issubset(FIELDS) or any(not isinstance(v, str) or len(v) > 16000 for v in values.values()):
            raise ValueError('Invalid equipment card fields')
        previous = self.get(address)
        values = {key: values.get(key, previous.get(key, '')) for key in FIELDS}
        record = dict(values, updated_at=datetime.now().astimezone().isoformat(), updated_by=actor)
        body = json.dumps(record, ensure_ascii=False)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT revision FROM cards WHERE ip=?', (address,)).fetchone()
            if (current[0] if current else 0) != revision:
                raise ValueError('This card changed in another window. Reload it before saving.')
            db.execute('INSERT OR REPLACE INTO cards VALUES (?,?,?)', (address, revision + 1, body))
            db.execute('INSERT INTO revisions(ip,body) VALUES (?,?)', (address, body))
        return revision + 1

    def history(self, address):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT body FROM revisions WHERE ip=? ORDER BY id DESC LIMIT 100', (address,))]


class EquipmentPanel(QWidget):
    saved = Signal()
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.store = EquipmentStore(atlas.data_dir / 'state' / 'equipment.sqlite3')
        self.address = ''
        self.revision = 0
        self.dirty = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Equipment register · saved on this workstation · discovery data is preserved')))
        self.devices = QComboBox()
        self.devices.setEditable(True)
        self.devices.lineEdit().setPlaceholderText(tr('Select or enter a device IP'))
        self.devices.addItems(sorted(set(atlas.inventory.devices) | {c['ip'] for c in self.store.cards()}, key=card_sort_key))
        layout.addWidget(self.devices)
        self.load_button = QPushButton(tr('Load Card'))
        self.load_button.clicked.connect(self.load)
        layout.addWidget(self.load_button)
        form = QFormLayout()
        self.fields = {}
        for name in FIELDS:
            field = QPlainTextEdit() if name == 'notes' else QLineEdit()
            if name == 'manufacturer': field.setPlaceholderText(tr('DEVA, Barix, Telos Alliance…'))
            if name == 'category': field.setPlaceholderText(tr('IP codec, encoder, decoder, processor…'))
            if name == 'management_url': field.setPlaceholderText('http://device-address:port/')
            field.textChanged.connect(self.changed)
            self.fields[name] = field
            form.addRow(tr(FIELD_LABELS.get(name, name.title())), field)
        layout.addLayout(form)
        self.save_button = QPushButton(tr('Save Card'))
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.status = QLabel(tr('Load a card before editing.'))
        layout.addWidget(self.status)
        self.signal_map = QPlainTextEdit()
        self.signal_map.setReadOnly(True)
        self.signal_map.setMaximumHeight(150)
        layout.addWidget(QLabel(tr('Known signal map')))
        layout.addWidget(self.signal_map)
        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        layout.addWidget(QLabel(tr('Saved revisions · newest first')))
        layout.addWidget(self.history_view)
        self.save_button.setEnabled(False)

    def changed(self):
        self.dirty = True

    def load(self):
        if not self.atlas.access.allowed('equipment'):
            return
        if self.dirty and self.address and QMessageBox.question(self, tr('Unsaved Card'),
                tr('Discard unsaved edits and load another card?')) != QMessageBox.Yes:
            return
        try:
            address = card_key(self.devices.currentText())
            card = self.store.get(address)
            self.address, self.revision = address, card['revision']
            for name, field in self.fields.items():
                (field.setPlainText if name == 'notes' else field.setText)(card[name])
            self.dirty = False
            self.save_button.setEnabled(True)
            self.status.setText(tr('{v0} · revision {v1} · {v2}', v0=address, v1=self.revision, v2=card.get('updated_at', 'New card')))
            self.render_signal_map(card)
            self.history_view.setPlainText('\n\n'.join(
                f'{r["updated_at"]} · {r["updated_by"]}\n' + '\n'.join(f'{k.title()}: {r.get(k, "")}' for k in FIELDS)
                for r in self.store.history(address)))
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, tr('Card unavailable'), str(exc))

    def render_signal_map(self, card):
        """Show only explicit engineering-map relationships, never guessed routes."""
        channel = card.get('livewire_channel', '').strip()
        rows = self.atlas.studio_map.connections_for(
            ip=self.address if is_network_card(self.address) else '',
            asset_number=card.get('asset_number', '').strip())
        if rows:
            lines = []
            for row in rows:
                channel_label = ('Livewire ' + row['channel']) if row['channel'] else row['link_type'].title()
                target = row['target_name'] + (f" · {row['target_input']}" if row['target_input'] else '')
                lines.append(f'{channel_label} · {row["source_name"]} → {target}\n{row["purpose"]} · {row["confidence"]}')
            self.signal_map.setPlainText('\n\n'.join(lines))
            return
        if is_network_card(self.address):
            node_number = self.address.rsplit('.', 1)[-1]
            rows = []
            for related in self.store.cards():
                value = related.get('livewire_channel', '').strip()
                if value.isdigit() and value[:-2] == node_number:
                    asset = related.get('asset_number', '')
                    label = related.get('name') or related['ip']
                    rows.append((int(value), f'{value} · {label}' + (f' · Microphone {asset}' if asset else '')))
            self.signal_map.setPlainText('\n'.join(text for _, text in sorted(rows)) or tr('No confirmed signals are recorded for this equipment.'))
        elif channel:
            self.signal_map.setPlainText(tr('Livewire channel: {v0}', v0=channel))
        else:
            self.signal_map.setPlainText(tr('No confirmed signal mapping is recorded.'))

    def save(self):
        if not self.address or not self.atlas.access.allowed('equipment'):
            return
        values = {name: (field.toPlainText() if name == 'notes' else field.text()).strip()
                  for name, field in self.fields.items()}
        try:
            user = self.atlas.access.user
            self.revision = self.store.save(self.address, values, self.revision, user['name'] if user else 'Setup')
            self.dirty = False
            self.atlas.record('Equipment card saved: ' + self.address, ip=self.address)
            self.devices.setCurrentText(self.address)
            self.load()
            self.saved.emit()
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, tr('Card not saved'), str(exc))
