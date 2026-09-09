"""Central accounts over TLS with explicit SHA-256 certificate pairing.

No automatic production listener. The director starts it from Administration.
The server remains available only while the hosting Atlas process is running.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import ssl
import threading
import time
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from access_control import AccessStore, PERMISSIONS, protect


def tls_identity(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    certificate, key_file, password_file = [directory / name for name in ('server.crt', 'server.key', 'key.dpapi')]
    existing = [p.exists() for p in (certificate, key_file, password_file)]
    if any(existing) and not all(existing):
        raise OSError('Server identity is incomplete. Restore all three server identity files from backup.')
    if not any(existing):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Axia Atlas Account Server')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
        password = secrets.token_bytes(32)
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password)))
        password_file.write_bytes(protect(password))
        certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(certificate.read_bytes())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(key_file), protect(password_file.read_bytes(), decrypt=True))
    return context, cert.fingerprint(hashes.SHA256()).hex()


def session_token(store):
    token = secrets.token_urlsafe(32)
    with store.db:
        store.db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        store.db.execute('INSERT INTO sessions VALUES(?,?,?)',
                         (hashlib.sha256(token.encode()).hexdigest(), store.user_id, time.time() + 8 * 3600))
    return token


class AccountServer:
    def __init__(self, database, directory, host='127.0.0.1', port=8443):
        self.database = str(database)
        context, self.fingerprint = tls_identity(directory)
        database_path = self.database
        self.stop_event = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # Never log Authorization headers or request bodies.

            def do_POST(self):
                store = None
                try:
                    if self.headers.get('Transfer-Encoding') or not self.headers.get('Content-Length', '').isdigit():
                        raise ValueError('A bounded JSON request is required.')
                    length = int(self.headers['Content-Length'])
                    if not 0 < length <= 65536:
                        raise ValueError('Request too large.')
                    self.connection.settimeout(5)
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError('Expected JSON object.')
                    store = AccessStore(database_path)
                    if self.path == '/login':
                        store.login(data['name'], data['password'])
                        result = {'user': store.user, 'token': session_token(store)}
                    else:
                        authorization = self.headers.get('Authorization', '')
                        token = authorization.removeprefix('Bearer ')
                        row = store.db.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires>?',
                            (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
                        if not authorization.startswith('Bearer ') or not row:
                            raise PermissionError('Session expired. Sign in again.')
                        store.user_id = row['user_id']
                        if not store.user:
                            raise PermissionError('Account disabled. Contact the technical director.')
                        result = self.dispatch(store, data, token)
                    self.reply(200, result)
                except PermissionError as exc:
                    self.reply(403, {'error': str(exc)})
                except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                    self.reply(400, {'error': 'Invalid or conflicting account details.' if isinstance(exc, (KeyError, TypeError, sqlite3.IntegrityError)) else str(exc)})
                except Exception:
                    self.reply(503, {'error': 'Account service could not complete the request.'})
                finally:
                    if store:
                        store.db.close()

            def dispatch(self, store, data, token):
                if self.path == '/session':
                    return {'user': store.user}
                if self.path == '/logout':
                    with store.db:
                        store.db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
                    store.logout()
                    return {}
                if self.path == '/password':
                    store.change_password(data['current'], data['password'])
                    return {'user': store.user, 'token': session_token(store)}
                if self.path == '/credentials':
                    if not store.allowed('device_ui'):
                        raise PermissionError('Device configuration access is not permitted.')
                    credentials = store.credentials(data['address'])
                    with store.db:
                        store.audit('Device credentials requested', data['address'])
                    return {'credentials': credentials}
                store.require_director()
                if self.path == '/users':
                    return {'users': store.users()}
                if self.path == '/users/save':
                    store.save_user(**data)
                elif self.path == '/profiles':
                    return {'profiles': store.profiles()}
                elif self.path == '/profiles/save':
                    store.save_profile(**data)
                elif self.path == '/profiles/remove':
                    store.remove_profile(data['profile_id'])
                elif self.path == '/audit':
                    return {'rows': store.audit_rows()}
                else:
                    raise ValueError('Unknown account operation.')
                return {}

            def reply(self, status, data):
                payload = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            # Bound parallel password hashing / connections. A slow connection
            # times out before TLS negotiation can stall all other clients.
            slots = threading.BoundedSemaphore(12)

            def process_request(self, request, address):
                if not self.slots.acquire(blocking=False):
                    request.close()
                    return
                super().process_request(request, address)

            def process_request_thread(self, request, address):
                try:
                    request.settimeout(5)
                    secured = context.wrap_socket(request, server_side=True)
                    super().process_request_thread(secured, address)
                except (OSError, ssl.SSLError):
                    request.close()
                finally:
                    self.slots.release()

        self.http = Server((host, port), Handler)
        self.port = self.http.server_port
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .1}, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


class RemoteAccess:
    configured = True

    def __init__(self, address, fingerprint):
        url = urlsplit(address.strip())
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            raise ValueError('Enter an HTTPS server address, for example https://192.0.2.10:8443.')
        self.host, self.port = url.hostname, url.port or 443
        self.fingerprint = fingerprint.lower().replace(':', '').replace(' ', '').strip()
        if len(self.fingerprint) != 64 or any(c not in '0123456789abcdef' for c in self.fingerprint):
            raise ValueError('Copy the full SHA-256 certificate fingerprint from the director’s server screen.')
        self.token = ''
        self._user = None

    @property
    def user(self):
        return self._user

    def call(self, path, data=None):
        # Pairing is verified before sending even the login body or session token.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = http.client.HTTPSConnection(self.host, self.port, context=context, timeout=3)
        try:
            connection.connect()
            der = connection.sock.getpeercert(binary_form=True)
            if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self.fingerprint):
                raise PermissionError('Server certificate does not match. No credentials were sent.')
            cert = x509.load_der_x509_certificate(der)
            now = datetime.now(timezone.utc)
            if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
                raise PermissionError('Server certificate is not currently valid.')
            connection.request('POST', path, json.dumps(data or {}).encode(),
                {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Server response too large.')
            result = json.loads(raw)
            if response.status != 200:
                raise PermissionError(result.get('error', 'Account request failed.'))
            return result
        except PermissionError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise ConnectionError('Account server unavailable. Check its address and whether Atlas is running there.') from exc
        finally:
            connection.close()

    def login(self, name, password):
        self._user = None
        self.token = ''
        result = self.call('/login', {'name': name, 'password': password})
        self._user, self.token = result['user'], result['token']
        return self.user

    def refresh(self):
        try:
            self._user = self.call('/session')['user']
        except Exception:
            self._user = None
            raise

    def allowed(self, permission):
        return bool(self.user and self.user['enabled'] and not self.user['must_change'] and
                    (self.user['director'] or permission in json.loads(self.user['permissions'])))

    def require_director(self):
        if not self.allowed('administration'):
            raise PermissionError('Only the technical director can manage accounts and credentials.')

    def logout(self):
        try:
            if self.token:
                self.call('/logout')
        finally:
            self._user, self.token = None, ''

    def users(self):
        return self.call('/users')['users']

    def save_user(self, **data):
        self.call('/users/save', data)

    def profiles(self):
        return self.call('/profiles')['profiles']

    def save_profile(self, **data):
        self.call('/profiles/save', data)

    def remove_profile(self, profile_id):
        self.call('/profiles/remove', {'profile_id': profile_id})

    def credentials(self, address):
        return self.call('/credentials', {'address': address})['credentials']

    def change_password(self, current, password):
        result = self.call('/password', {'current': current, 'password': password})
        self._user, self.token = result['user'], result['token']

    def audit_rows(self):
        return self.call('/audit')['rows']
