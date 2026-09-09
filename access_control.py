"""Local Atlas accounts and explicitly assigned device credentials.

Windows DPAPI uses the current Windows user scope. This is an application access
policy, not an isolation boundary against users who control the Windows account.
"""
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit


PERMISSIONS = {
    'network': 'Network discovery and device information',
    'audio': 'Audio monitoring and recording playback',
    'record': 'Record audio',
    'device_ui': 'Full device configuration web interface',
    'library': 'View manuals and firmware library',
    'downloads': 'Download manuals, firmware and software',
    'events': 'View and export events / receive syslog',
    'diagnostics': 'Health, change history and diagnostic reports',
    'ollama': 'Engineering Assistant (Ollama)',
}


def origin(value):
    value = value.strip()
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Enter a device IP or HTTP(S) address without a path or password.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    return f'{parsed.scheme}://{host}:{port}'


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise OSError('Device password storage requires Windows data protection.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    memory = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(memory, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(incoming), 'Axia Atlas device credentials', None, None, None, 1, ctypes.byref(outgoing))
    function.restype = wintypes.BOOL
    if not function(*args):
        raise OSError('Windows could not unlock device credentials. Use the Windows account that saved them.')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600_000)


def validate_password(password):
    if not 10 <= len(password) <= 256:
        raise ValueError('Use an Atlas password between 10 and 256 characters.')


class AccessStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                salt BLOB NOT NULL, digest BLOB NOT NULL, director INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1, permissions TEXT NOT NULL,
                must_change INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, secret BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS assignments (
                origin TEXT PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
        ''')
        self.user_id = None

    @property
    def configured(self):
        return self.db.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None

    @property
    def user(self):
        if self.user_id is None:
            return None
        row = self.db.execute('SELECT id,name,director,enabled,permissions,must_change FROM users WHERE id=?', (self.user_id,)).fetchone()
        return dict(row) if row and row['enabled'] else None

    def allowed(self, permission):
        if not self.configured:
            return True  # Clearly labelled initial setup; no default account/password.
        user = self.user
        return bool(user and not user['must_change'] and
                    (user['director'] or permission in json.loads(user['permissions'])))

    def require_director(self):
        user = self.user
        if not user or not user['director'] or user['must_change']:
            raise PermissionError('Only the technical director can manage accounts and credentials.')

    def audit(self, action, target='', actor=None):
        user = self.user
        self.db.execute('INSERT INTO audit(actor,action,target) VALUES(?,?,?)',
                        (actor or (user['name'] if user else 'Signed out'), action, target))

    def setup(self, name, password):
        validate_password(password)
        name = self.clean_name(name)
        salt = os.urandom(32)
        digest = password_hash(password, salt)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.configured:
                raise PermissionError('The director account already exists. Sign in.')
            cursor = self.db.execute('INSERT INTO users(name,salt,digest,director,permissions) VALUES(?,?,?,1,?)',
                                     (name, salt, digest, json.dumps(list(PERMISSIONS))))
            self.user_id = cursor.lastrowid
            self.audit('Director account created')

    @staticmethod
    def clean_name(name):
        name = name.strip().casefold()
        if not name or len(name) > 64 or any(not (c.isalnum() or c in '._-') for c in name):
            raise ValueError('Username: 1–64 letters, numbers, dots, underscores or hyphens.')
        return name

    def login(self, name, password):
        self.user_id = None
        name = name.strip().casefold()
        row = self.db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
        if row and row['locked_until'] > time.time():
            raise PermissionError('Too many attempts. Try again in one minute.')
        digest = password_hash(password[:257], row['salt'] if row else bytes(32))
        good = bool(row and row['enabled'] and hmac.compare_digest(digest, row['digest']))
        with self.db:
            if not good:
                if row:
                    failures = row['failures'] + 1
                    self.db.execute('UPDATE users SET failures=?,locked_until=? WHERE id=?',
                                    (failures, time.time() + 60 if failures >= 5 else 0, row['id']))
                self.audit('Sign-in rejected', actor=name[:64] or 'Unknown')
            else:
                self.user_id = row['id']
                self.db.execute('UPDATE users SET failures=0,locked_until=0 WHERE id=?', (self.user_id,))
                self.audit('Signed in')
        if not good:
            raise PermissionError('Username or password is incorrect, or the account is disabled.')
        return self.user

    def logout(self):
        with self.db:
            self.audit('Signed out')
        self.user_id = None

    def users(self):
        self.require_director()
        return [dict(row) for row in self.db.execute('SELECT id,name,director,enabled,permissions,must_change FROM users ORDER BY director DESC,name')]

    def save_user(self, name, permissions, enabled=True, password=None, user_id=None):
        self.require_director()
        name = self.clean_name(name)
        permissions = set(permissions)
        if not permissions <= PERMISSIONS.keys():
            raise ValueError('Unknown permission.')
        if 'record' in permissions and 'audio' not in permissions:
            raise ValueError('Recording requires Audio monitoring permission.')
        if 'downloads' in permissions and 'library' not in permissions:
            raise ValueError('Downloads require Library permission.')
        with self.db:
            if user_id is not None:
                old = self.db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
                if not old or old['director']:
                    raise PermissionError('Use Change My Password for the director account.')
                self.db.execute('UPDATE users SET name=?,enabled=?,permissions=? WHERE id=?',
                                (name, bool(enabled), json.dumps(sorted(permissions)), user_id))
            else:
                if password is None:
                    raise ValueError('Enter an initial password.')
                validate_password(password)
                salt = os.urandom(32)
                user_id = self.db.execute('INSERT INTO users(name,salt,digest,permissions,enabled,must_change) VALUES(?,?,?,?,?,1)',
                    (name, salt, password_hash(password, salt), json.dumps(sorted(permissions)), bool(enabled))).lastrowid
            if password is not None:
                validate_password(password)
                salt = os.urandom(32)
                self.db.execute('UPDATE users SET salt=?,digest=?,must_change=1,failures=0,locked_until=0 WHERE id=?',
                    (salt, password_hash(password, salt), user_id))
                self.db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            self.audit('User permissions/account updated', name)

    def change_password(self, current, password):
        user = self.user
        if not user:
            raise PermissionError('Sign in first.')
        row = self.db.execute('SELECT * FROM users WHERE id=?', (self.user_id,)).fetchone()
        if not hmac.compare_digest(password_hash(current, row['salt']), row['digest']):
            raise PermissionError('Current Atlas password is incorrect.')
        validate_password(password)
        if password == current:
            raise ValueError('Choose a different password.')
        salt = os.urandom(32)
        with self.db:
            self.db.execute('UPDATE users SET salt=?,digest=?,must_change=0 WHERE id=?',
                            (salt, password_hash(password, salt), self.user_id))
            self.db.execute('DELETE FROM sessions WHERE user_id=?', (self.user_id,))
            self.audit('Atlas password changed')

    def profiles(self):
        self.require_director()
        result = []
        for row in self.db.execute('SELECT id,name FROM profiles ORDER BY name'):
            result.append(dict(row, addresses=[r[0] for r in self.db.execute(
                'SELECT origin FROM assignments WHERE profile_id=? ORDER BY origin', (row['id'],))]))
        return result

    def save_profile(self, name, username, password, addresses, profile_id=None):
        self.require_director()
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a profile name (up to 100 characters).')
        addresses = sorted({origin(address) for address in addresses if address.strip()})
        if not addresses:
            raise ValueError('Assign at least one device address.')
        secret = protect(json.dumps([username, password]).encode()) if password is not None else None
        with self.db:
            if profile_id is None:
                if secret is None:
                    raise ValueError('Enter the device username and password.')
                profile_id = self.db.execute('INSERT INTO profiles(name,secret) VALUES(?,?)', (name, secret)).lastrowid
            else:
                if not self.db.execute('SELECT 1 FROM profiles WHERE id=?', (profile_id,)).fetchone():
                    raise ValueError('Profile no longer exists.')
                self.db.execute('UPDATE profiles SET name=? WHERE id=?', (name, profile_id))
                if secret is not None:
                    self.db.execute('UPDATE profiles SET secret=? WHERE id=?', (secret, profile_id))
            for address in addresses:
                existing = self.db.execute('SELECT profile_id FROM assignments WHERE origin=?', (address,)).fetchone()
                if existing and existing[0] != profile_id:
                    raise ValueError(f'{address} already belongs to another profile. Remove that assignment first.')
            self.db.execute('DELETE FROM assignments WHERE profile_id=?', (profile_id,))
            self.db.executemany('INSERT INTO assignments(origin,profile_id) VALUES(?,?)', [(a, profile_id) for a in addresses])
            self.audit('Device credential profile saved', name)

    def remove_profile(self, profile_id):
        self.require_director()
        with self.db:
            self.db.execute('DELETE FROM profiles WHERE id=?', (profile_id,))
            self.audit('Device credential profile removed', str(profile_id))

    def credentials(self, address):
        if not self.configured or not self.allowed('device_ui'):
            return None
        row = self.db.execute('SELECT p.secret FROM assignments a JOIN profiles p ON p.id=a.profile_id WHERE a.origin=?', (origin(address),)).fetchone()
        return tuple(json.loads(protect(bytes(row[0]), decrypt=True).decode())) if row else None

    def audit_rows(self):
        self.require_director()
        return [dict(row) for row in self.db.execute('SELECT at,actor,action,target FROM audit ORDER BY id DESC LIMIT 1000')]
