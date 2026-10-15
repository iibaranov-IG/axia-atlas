"""Confirmed studio topology, kept separately from transient network discovery."""
from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class StudioMapStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                ip TEXT, axia_number TEXT, manufacturer TEXT, model TEXT,
                role TEXT NOT NULL, confidence TEXT NOT NULL, origin TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS signal_routes (
                livewire_channel TEXT PRIMARY KEY, source_asset_id TEXT NOT NULL,
                node_asset_id TEXT NOT NULL, node_stream INTEGER NOT NULL,
                purpose TEXT NOT NULL, confidence TEXT NOT NULL, origin TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_asset_id) REFERENCES assets(asset_id),
                FOREIGN KEY(node_asset_id) REFERENCES assets(asset_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS direct_routes (
                source_asset_id TEXT NOT NULL, target_asset_id TEXT NOT NULL,
                connection_type TEXT NOT NULL, target_input TEXT NOT NULL,
                purpose TEXT NOT NULL, confidence TEXT NOT NULL, origin TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_asset_id,target_asset_id,connection_type,target_input),
                FOREIGN KEY(source_asset_id) REFERENCES assets(asset_id),
                FOREIGN KEY(target_asset_id) REFERENCES assets(asset_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS engineering_facts (
                fact_key TEXT PRIMARY KEY, fact_value TEXT NOT NULL,
                confidence TEXT NOT NULL, origin TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def add_asset(self, asset_id, *, kind, name, role, ip='', axia_number='', manufacturer='', model='',
                  confidence='confirmed', origin='Engineering interview', replace=False):
        values = (asset_id, kind, name, ip, axia_number, manufacturer, model, role, confidence, origin, self.now())
        statement = ('INSERT OR REPLACE' if replace else 'INSERT OR IGNORE') + ''' INTO assets
            (asset_id,kind,name,ip,axia_number,manufacturer,model,role,confidence,origin,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)'''
        with self.connection() as db:
            db.execute(statement, values)

    def add_signal(self, channel, *, source_asset_id, node_asset_id, node_stream, purpose,
                   confidence='confirmed', origin='Engineering interview', replace=False):
        channel = str(channel)
        if not channel.isdigit() or int(node_stream) < 1:
            raise ValueError('Livewire channel and node stream must be positive numbers.')
        values = (channel, source_asset_id, node_asset_id, int(node_stream), purpose, confidence, origin, self.now())
        statement = ('INSERT OR REPLACE' if replace else 'INSERT OR IGNORE') + ''' INTO signal_routes
            (livewire_channel,source_asset_id,node_asset_id,node_stream,purpose,confidence,origin,updated_at)
            VALUES (?,?,?,?,?,?,?,?)'''
        with self.connection() as db:
            db.execute(statement, values)

    def routes_for_node(self, asset_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute('''SELECT r.*, a.name AS source_name, a.axia_number AS asset_number
                FROM signal_routes r JOIN assets a ON a.asset_id=r.source_asset_id
                WHERE r.node_asset_id=? ORDER BY CAST(r.livewire_channel AS INTEGER)''', (asset_id,))]

    def topology_rows(self):
        """Return only sourced, operator-readable links in the confirmed studio map."""
        with self.connection() as db:
            signals = [dict(row) for row in db.execute('''SELECT
                    r.livewire_channel AS channel, a.name AS source_name,
                    n.name AS target_name, r.node_stream AS target_input,
                    r.purpose, r.confidence, r.origin, 'livewire' AS link_type
                FROM signal_routes r
                JOIN assets a ON a.asset_id=r.source_asset_id
                JOIN assets n ON n.asset_id=r.node_asset_id
                ORDER BY CAST(r.livewire_channel AS INTEGER)''')]
            direct = [dict(row) for row in db.execute('''SELECT
                    '' AS channel, a.name AS source_name, n.name AS target_name,
                    r.target_input, r.purpose, r.confidence, r.origin,
                    r.connection_type AS link_type
                FROM direct_routes r
                JOIN assets a ON a.asset_id=r.source_asset_id
                JOIN assets n ON n.asset_id=r.target_asset_id
                ORDER BY a.name, n.name, r.target_input''')]
        for row in direct:
            match = re.search(r'\bLivewire\s+(\d+)\b', row['target_input'])
            if match:
                row['channel'] = match.group(1)
        return signals + direct

    def connections_for(self, *, ip='', asset_number=''):
        """Find explicit map links for one equipment card without guessing a route."""
        with self.connection() as db:
            asset_ids = set()
            if ip:
                asset_ids.update(row[0] for row in db.execute('SELECT asset_id FROM assets WHERE ip=?', (ip,)))
            if asset_number:
                asset_ids.update(row[0] for row in db.execute(
                    'SELECT asset_id FROM assets WHERE axia_number=?', (str(asset_number),)))
            if not asset_ids:
                return []
            placeholders = ','.join('?' for _ in asset_ids)
            rows = [dict(row) for row in db.execute(f'''SELECT r.livewire_channel AS channel,
                    a.name AS source_name, n.name AS target_name, r.node_stream AS target_input,
                    r.purpose, r.confidence, r.origin, 'Livewire' AS link_type
                FROM signal_routes r JOIN assets a ON a.asset_id=r.source_asset_id
                JOIN assets n ON n.asset_id=r.node_asset_id
                WHERE r.source_asset_id IN ({placeholders}) OR r.node_asset_id IN ({placeholders})
                ORDER BY CAST(r.livewire_channel AS INTEGER)''', tuple(asset_ids) * 2)]
            rows += [dict(row) for row in db.execute(f'''SELECT '' AS channel,
                    a.name AS source_name, n.name AS target_name, r.target_input,
                    r.purpose, r.confidence, r.origin, r.connection_type AS link_type
                FROM direct_routes r JOIN assets a ON a.asset_id=r.source_asset_id
                JOIN assets n ON n.asset_id=r.target_asset_id
                WHERE r.source_asset_id IN ({placeholders}) OR r.target_asset_id IN ({placeholders})
                ORDER BY a.name, n.name, r.target_input''', tuple(asset_ids) * 2)]
        return rows

    def add_direct_route(self, *, source_asset_id, target_asset_id, connection_type, target_input,
                         purpose, confidence='confirmed', origin='Engineering interview', replace=False):
        values = (source_asset_id, target_asset_id, connection_type, target_input, purpose,
                  confidence, origin, self.now())
        statement = ('INSERT OR REPLACE' if replace else 'INSERT OR IGNORE') + ''' INTO direct_routes
            (source_asset_id,target_asset_id,connection_type,target_input,purpose,confidence,origin,updated_at)
            VALUES (?,?,?,?,?,?,?,?)'''
        with self.connection() as db:
            db.execute(statement, values)

    def add_fact(self, key, value, *, confidence='confirmed', origin='Engineering interview', replace=False):
        values = (key, value, confidence, origin, self.now())
        statement = ('INSERT OR REPLACE' if replace else 'INSERT OR IGNORE') + ''' INTO engineering_facts
            (fact_key,fact_value,confidence,origin,updated_at) VALUES (?,?,?,?,?)'''
        with self.connection() as db:
            db.execute(statement, values)

    def remove_fact(self, key):
        with self.connection() as db:
            db.execute('DELETE FROM engineering_facts WHERE fact_key=?', (key,))

    def summary(self, budget=1800):
        """Bounded, sourced facts for the advisory model; no device measurements."""
        with self.connection() as db:
            assets = [dict(row) for row in db.execute('SELECT * FROM assets ORDER BY kind, asset_id')]
            routes = [dict(row) for row in db.execute('''SELECT r.*, a.name AS source_name, n.name AS node_name
                FROM signal_routes r JOIN assets a ON a.asset_id=r.source_asset_id
                JOIN assets n ON n.asset_id=r.node_asset_id ORDER BY CAST(r.livewire_channel AS INTEGER)''')]
            direct = [dict(row) for row in db.execute('''SELECT r.*, a.name AS source_name, n.name AS target_name
                FROM direct_routes r JOIN assets a ON a.asset_id=r.source_asset_id
                JOIN assets n ON n.asset_id=r.target_asset_id ORDER BY r.source_asset_id''')]
            facts = [dict(row) for row in db.execute('SELECT * FROM engineering_facts ORDER BY fact_key')]
        lines = ['Confirmed studio map supplied by engineering; not live device telemetry.']
        # Signal routes answer operational questions first; the asset inventory
        # follows only while room remains in the bounded advisory context.
        for route in routes:
            lines.append(f"{route['livewire_channel']}: {route['source_name']} → {route['node_name']} stream {route['node_stream']} ({route['purpose']})")
        for route in direct:
            lines.append(f"Direct {route['connection_type']}: {route['source_name']} → {route['target_name']} {route['target_input']} ({route['purpose']})")
        for fact in facts:
            lines.append('Engineering fact: ' + fact['fact_value'])
        for asset in assets:
            parts = [asset['name'], asset['kind'], asset['role']]
            if asset['ip']: parts.append('IP ' + asset['ip'])
            if asset['axia_number']: parts.append('Axia ' + asset['axia_number'])
            lines.append(' · '.join(parts))
        text = '\n'.join(lines)
        return text[:budget]
