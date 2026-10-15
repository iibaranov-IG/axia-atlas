"""Transactional player state. Source media are referenced, never modified."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class PlayerStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 1:
            self.db.close()
            raise ValueError('This player database requires a newer application version.')
        with self.db:
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL, duration_ms INTEGER NOT NULL,
                    sample_rate INTEGER NOT NULL, channels INTEGER NOT NULL,
                    codec TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS playlists (
                    name TEXT PRIMARY KEY, items TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jingles (
                    slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 0 AND 7),
                    media_id INTEGER NOT NULL REFERENCES media(id));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, time TEXT NOT NULL,
                    action TEXT NOT NULL, detail TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')

    def close(self):
        self.db.close()

    def put_media(self, values):
        fields = ('path', 'title', 'duration_ms', 'sample_rate', 'channels',
                  'codec', 'size', 'mtime_ns', 'status', 'error')
        with self.db:
            self.db.execute('INSERT INTO media (' + ','.join(fields) + ') VALUES (' +
                            ','.join('?' for _ in fields) + ') ON CONFLICT(path) DO UPDATE SET ' +
                            ','.join(f'{key}=excluded.{key}' for key in fields[1:]),
                            [values[key] for key in fields])
        return self.db.execute('SELECT id FROM media WHERE path=?', (values['path'],)).fetchone()[0]

    def media(self, media_id):
        row = self.db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
        return dict(row) if row else None

    def library(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM media ORDER BY title COLLATE NOCASE, id')]

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                            (key, json.dumps(value, ensure_ascii=False)))

    def save_playlist(self, name, items):
        name = name.strip()
        if not name:
            raise ValueError('Playlist name is empty')
        if any(not self.media(media_id) for media_id in items):
            raise ValueError('Unknown media in playlist')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO playlists VALUES (?,?)', (name, json.dumps(items)))

    def playlists(self):
        return [row[0] for row in self.db.execute('SELECT name FROM playlists ORDER BY name')]

    def playlist(self, name):
        row = self.db.execute('SELECT items FROM playlists WHERE name=?', (name,)).fetchone()
        return json.loads(row[0]) if row else []

    def assign_jingle(self, slot, media_id):
        with self.db:
            if media_id is None:
                self.db.execute('DELETE FROM jingles WHERE slot=?', (slot,))
            else:
                self.db.execute('INSERT OR REPLACE INTO jingles VALUES (?,?)', (slot, media_id))

    def jingles(self):
        return dict(self.db.execute('SELECT slot,media_id FROM jingles'))

    def event(self, action, detail):
        with self.db:
            self.db.execute('INSERT INTO events(time,action,detail) VALUES (?,?,?)',
                            (datetime.now(timezone.utc).isoformat(timespec='milliseconds'), action, detail))

    def events(self, limit=500):
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))]
