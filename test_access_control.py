import base64
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog
from access_control import AccessStore, protect
from access_server import AccountServer, RemoteAccess
from administration import SignInDialog, UserDialog, ProfileDialog
from main import Atlas


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = AccessStore(self.root / 'accounts.sqlite3')
        self.store.setup('director', 'Director-test-123!')

    def tearDown(self):
        self.store.db.close()
        self.temporary.cleanup()

    def test_dpapi_accounts_no_plaintext_last_director_and_permissions(self):
        secret = b'fixture-secret-only'
        encrypted = protect(secret)
        self.assertNotIn(secret, encrypted)
        self.assertEqual(protect(encrypted, decrypt=True), secret)
        with self.assertRaises(PermissionError):
            self.store.save_user('director', [], False, user_id=self.store.user['id'])
        self.store.save_user('engineer', ['audio'], password='Temporary-123!')
        self.store.login('engineer', 'Temporary-123!')
        self.assertFalse(self.store.allowed('audio'))
        self.store.change_password('Temporary-123!', 'Personal-123!')
        self.assertTrue(self.store.allowed('audio'))
        self.assertFalse(self.store.allowed('record'))
        self.assertFalse(self.store.allowed('device_ui'))
        with self.assertRaises(PermissionError):
            self.store.users()
        raw = (self.root / 'accounts.sqlite3').read_bytes()
        for password in (b'Director-test-123!', b'Temporary-123!', b'Personal-123!'):
            self.assertNotIn(password, raw)

    def test_tls_multiple_workstations_permissions_revocation_and_pinning(self):
        server = AccountServer(self.root / 'accounts.sqlite3', self.root / 'tls', port=0)
        server.start()
        try:
            address = f'https://127.0.0.1:{server.port}'
            director = RemoteAccess(address, server.fingerprint)
            engineer = RemoteAccess(address, server.fingerprint)
            director.login('director', 'Director-test-123!')
            director.save_user(name='engineer', permissions=['audio', 'device_ui'], password='Temporary-123!')
            engineer.login('engineer', 'Temporary-123!')
            old_token = engineer.token
            engineer.change_password('Temporary-123!', 'Personal-123!')
            stale = RemoteAccess(address, server.fingerprint)
            stale.token = old_token
            with self.assertRaises(PermissionError):
                stale.refresh()
            director.save_profile(name='Test nodes', username='fixture', password='Device-test-123!', addresses=['192.0.2.1', '192.0.2.2'])
            self.assertEqual(engineer.credentials('http://192.0.2.1'), ['fixture', 'Device-test-123!'])
            self.assertIsNone(engineer.credentials('http://192.0.2.3'))
            with self.assertRaises(PermissionError):
                engineer.save_user(name='intruder', permissions=['device_ui'], password='Temporary-123!')
            user = next(user for user in director.users() if user['name'] == 'engineer')
            director.save_user(name='engineer', permissions=['audio'], user_id=user['id'])
            with self.assertRaises(PermissionError):
                engineer.credentials('http://192.0.2.1')
            engineer.refresh()
            self.assertFalse(engineer.allowed('device_ui'))
            bad = RemoteAccess(address, '0' * 64)
            count = len(director.audit_rows())
            with self.assertRaisesRegex(PermissionError, 'No credentials were sent'):
                bad.login('director', 'Director-test-123!')
            self.assertEqual(count, len(director.audit_rows()))
            director.save_user(name='engineer', permissions=[], enabled=False, user_id=user['id'])
            with self.assertRaises(PermissionError):
                engineer.refresh()
            self.assertIsNone(engineer.user)
            self.assertNotIn(b'Device-test-123!', (self.root / 'accounts.sqlite3').read_bytes())
            director.logout()
            with self.assertRaises(PermissionError):
                director.call('/users')
        finally:
            server.stop()

    def test_profile_assignment_conflict_rolls_back_and_retry_lockout(self):
        self.store.save_profile('One', 'fixture', 'test', ['192.0.2.1'])
        with self.assertRaises(ValueError):
            self.store.save_profile('Two', 'fixture', 'test2', ['192.0.2.1'])
        self.assertEqual(len(self.store.profiles()), 1)
        for _ in range(5):
            with self.assertRaises(PermissionError):
                self.store.login('director', 'incorrect')
        with self.assertRaisesRegex(PermissionError, 'Too many'):
            self.store.login('director', 'Director-test-123!')


class AdministrationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_gui_create_user_profile_login_and_block_actual_functions(self):
        with tempfile.TemporaryDirectory() as folder:
            window = Atlas(folder)
            try:
                setup = SignInDialog(window.access, window, setup=True)
                setup.username.setText('director')
                setup.password.setText('Director-test-123!')
                setup.confirm.setText('Director-test-123!')
                setup.submit()
                self.assertEqual(setup.result(), QDialog.Accepted)
                user = UserDialog(window.access, window)
                user.name.setText('observer')
                user.checks['audio'].setChecked(True)
                user.password.setText('Temporary-123!')
                user.confirm.setText('Temporary-123!')
                user.submit()
                self.assertEqual(user.result(), QDialog.Accepted)
                profile = ProfileDialog(window.access, window)
                profile.name.setText('Studio nodes')
                profile.username.setText('fixture')
                profile.password.setText('Device-test-123!')
                profile.addresses.setPlainText('192.0.2.1\n192.0.2.2')
                profile.submit()
                self.assertEqual(profile.result(), QDialog.Accepted)
                self.assertEqual(len(window.access.profiles()[0]['addresses']), 2)
                window.access.logout()
                window.access.login('observer', 'Temporary-123!')
                window.access.change_password('Temporary-123!', 'Personal-123!')
                window.apply_permissions()
                window.show()
                self.app.processEvents()

                self.assertFalse(window.health.isEnabled())
                self.assertFalse(window.player.record_button.isEnabled())
                item = window.network.ensure_device('http://192.0.2.1/', {'ip': '192.0.2.1', 'name': 'fixture'})
                count = window.tabs.count()
                window.open_device(item)
                window.queue_inspection('192.0.2.1')
                window.player.start_recording(str(Path(folder) / 'denied.wav'))
                self.assertEqual(window.tabs.count(), count)
                self.assertEqual(window.inspect_jobs, {})
                self.assertFalse((Path(folder) / 'denied.wav').exists())
                self.assertTrue(window.end_session())
                self.assertFalse(window.tabs.isVisible())
            finally:
                window.close()
                self.app.processEvents()


    def test_two_desktop_clients_refresh_revoked_permissions_and_lock_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = AccessStore(root / 'central.sqlite3')
            store.setup('director', 'Director-test-123!')
            store.save_user('engineer', ['audio', 'device_ui', 'library'], password='Temporary-123!')
            server = AccountServer(root / 'central.sqlite3', root / 'tls', port=0)
            server.start()
            director_window = Atlas(root / 'director')
            engineer_window = Atlas(root / 'engineer')
            try:
                address = f'https://127.0.0.1:{server.port}'
                director = RemoteAccess(address, server.fingerprint)
                director.login('director', 'Director-test-123!')
                engineer = RemoteAccess(address, server.fingerprint)
                engineer.login('engineer', 'Temporary-123!')
                engineer.change_password('Temporary-123!', 'Personal-123!')
                director_window.access = director
                engineer_window.access = engineer
                director_window.apply_permissions()
                engineer_window.apply_permissions()
                director_window.show()
                engineer_window.show()
                self.app.processEvents()
                self.assertTrue(engineer_window.access.allowed('device_ui'))
                user = next(u for u in director.users() if u['name'] == 'engineer')
                editor = UserDialog(director, director_window, user)
                editor.checks['device_ui'].setChecked(False)
                editor.checks['library'].setChecked(False)
                editor.submit()
                self.assertEqual(editor.result(), QDialog.Accepted)
                engineer_window.refresh_session()
                loop = QEventLoop()
                engineer_window.session_poll.finished.connect(loop.quit)
                QTimer.singleShot(5000, loop.quit)
                loop.exec()
                self.assertFalse(engineer_window.access.allowed('device_ui'))
                self.assertFalse(engineer_window.left_tabs.isTabEnabled(2))
                server.stop()
                server = None
                self.app.processEvents()
                engineer_window.refresh_session()
                if engineer_window.session_poll:
                    engineer_window.session_poll.finished.connect(loop.quit)
                    QTimer.singleShot(5000, loop.quit)
                    loop.exec()
                self.assertFalse(engineer_window.tabs.isVisible())
                self.assertIsNone(engineer.user)
            finally:
                director_window.close()
                engineer_window.close()
                self.app.processEvents()
                if server:
                    server.stop()
                store.db.close()
    def test_saved_credentials_real_webview_and_no_cache_across_logout(self):
        accepted = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'fixture:Device-test-123!').decode():
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Basic realm="Fixture"')
                    self.end_headers()
                else:
                    accepted.append(True)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<html><title>Saved credentials accepted</title>Configuration</html>')
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                window = Atlas(folder)
                try:
                    store = window.access
                    store.setup('director', 'Director-test-123!')
                    address = f'http://127.0.0.1:{server.server_port}'
                    store.save_profile('Fixture', 'fixture', 'Device-test-123!', [address])
                    item = window.network.ensure_device(address + '/', {'ip': '127.0.0.1', 'name': 'Fixture'})
                    with patch('device_auth.request_credentials', return_value=None) as prompt:
                        window.open_device(item)
                        browser = window.tabs.currentWidget()
                        loop = QEventLoop()
                        browser.loadFinished.connect(loop.quit)
                        QTimer.singleShot(5000, loop.quit)
                        loop.exec()
                        self.assertEqual(browser.title(), 'Saved credentials accepted')
                        prompt.assert_not_called()
                    window.end_session()
                    self.app.processEvents()
                    store.login('director', 'Director-test-123!')
                    store.remove_profile(store.profiles()[0]['id'])
                    previous = len(accepted)
                    with patch('device_auth.request_credentials', return_value=None) as prompt:
                        window.open_device(item)
                        browser = window.tabs.currentWidget()
                        browser.loadFinished.connect(loop.quit)
                        QTimer.singleShot(5000, loop.quit)
                        loop.exec()
                        self.assertTrue(prompt.called)
                        self.assertEqual(len(accepted), previous)
                finally:
                    window.close()
                    self.app.processEvents()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
