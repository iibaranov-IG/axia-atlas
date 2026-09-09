"""Operator-facing account, permission and server configuration dialogs."""
import json
import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QLabel, QMessageBox, QCheckBox, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QWidget, QTreeWidget, QTreeWidgetItem, QPlainTextEdit, QSpinBox)
from access_control import PERMISSIONS
from access_server import AccountServer, RemoteAccess

ERRORS = (ValueError, PermissionError, OSError, sqlite3.Error)


def password_field(name):
    field = QLineEdit()
    field.setObjectName(name)
    field.setEchoMode(QLineEdit.Password)
    field.setMaxLength(256)
    return field


class SignInDialog(QDialog):
    def __init__(self, store, parent=None, setup=False):
        super().__init__(parent)
        self.store, self.setup = store, setup
        self.setWindowTitle('Create Technical Director' if setup else 'Sign In to Atlas')
        form = QFormLayout(self)
        self.username = QLineEdit()
        self.username.setObjectName('atlas_username')
        self.password = password_field('atlas_password')
        self.confirm = password_field('atlas_confirm')
        form.addRow(QLabel('Create the director account on the computer that will host the account server.'
                           if setup else 'Use the account provided by your technical director.'))
        form.addRow('Username', self.username)
        form.addRow('Password', self.password)
        if setup:
            form.addRow('Confirm password', self.confirm)
            form.addRow(QLabel('Atlas passwords: at least 10 characters. Device passwords are separate.'))
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def submit(self):
        try:
            if self.setup:
                if self.password.text() != self.confirm.text():
                    raise ValueError('Passwords do not match.')
                self.store.setup(self.username.text(), self.password.text())
            else:
                self.store.login(self.username.text(), self.password.text())
                if self.store.user['must_change']:
                    dialog = PasswordDialog(self.store, self, required=True)
                    if dialog.exec() != QDialog.Accepted:
                        self.store.logout()
                        return
        except ERRORS as exc:
            self.error.setText(str(exc))
            self.password.clear()
            return
        self.password.clear()
        self.confirm.clear()
        self.accept()


class PasswordDialog(QDialog):
    def __init__(self, store, parent=None, required=False):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Change Your Atlas Password')
        form = QFormLayout(self)
        if required:
            form.addRow(QLabel('Replace your temporary password before using Atlas.'))
        self.current = password_field('current_password')
        self.new = password_field('new_password')
        self.confirm = password_field('confirm_password')
        for title, field in [('Current password', self.current), ('New password', self.new), ('Confirm', self.confirm)]:
            form.addRow(title, field)
        self.error = QLabel()
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def submit(self):
        try:
            if self.new.text() != self.confirm.text():
                raise ValueError('Passwords do not match.')
            self.store.change_password(self.current.text(), self.new.text())
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        for field in (self.current, self.new, self.confirm):
            field.clear()
        self.accept()


class UserDialog(QDialog):
    def __init__(self, store, parent=None, user=None):
        super().__init__(parent)
        self.store, self.user = store, user
        self.setWindowTitle('Edit Engineer' if user else 'Create Engineer')
        form = QFormLayout(self)
        self.name = QLineEdit(user['name'] if user else '')
        self.enabled = QCheckBox('Account enabled')
        self.enabled.setChecked(bool(user['enabled']) if user else True)
        form.addRow('Username', self.name)
        form.addRow(self.enabled)
        self.checks = {}
        permissions = json.loads(user['permissions']) if user else []
        for key, title in PERMISSIONS.items():
            check = QCheckBox(title)
            check.setChecked(key in permissions)
            self.checks[key] = check
            form.addRow(check)
        note = QLabel('Device web access permits all actions supported by that device web interface.\n'
                      'Backup, restoration, firmware installation and scenarios are not implemented yet.')
        note.setWordWrap(True)
        form.addRow(note)
        self.reset = QCheckBox('Set temporary password (change required at next sign-in)')
        self.reset.setChecked(user is None)
        self.reset.setEnabled(user is not None)
        self.password = password_field('temporary_password')
        self.confirm = password_field('temporary_confirm')
        self.password.setEnabled(user is None)
        self.confirm.setEnabled(user is None)
        self.reset.toggled.connect(self.password.setEnabled)
        self.reset.toggled.connect(self.confirm.setEnabled)
        form.addRow(self.reset)
        form.addRow('Temporary password', self.password)
        form.addRow('Confirm', self.confirm)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def submit(self):
        try:
            if self.reset.isChecked() and self.password.text() != self.confirm.text():
                raise ValueError('Passwords do not match.')
            self.store.save_user(name=self.name.text(), permissions=[key for key, check in self.checks.items() if check.isChecked()],
                enabled=self.enabled.isChecked(), password=self.password.text() if self.reset.isChecked() else None,
                user_id=self.user['id'] if self.user else None)
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        self.password.clear()
        self.confirm.clear()
        self.accept()


class ProfileDialog(QDialog):
    def __init__(self, store, parent=None, profile=None):
        super().__init__(parent)
        self.store, self.profile = store, profile
        self.setWindowTitle('Device Credential Profile')
        self.resize(530, 460)
        form = QFormLayout(self)
        self.name = QLineEdit(profile['name'] if profile else '')
        self.replace = QCheckBox('Replace saved username and password')
        self.replace.setChecked(profile is None)
        self.replace.setEnabled(profile is not None)
        self.username = QLineEdit()
        self.username.setMaxLength(256)
        self.password = password_field('profile_password')
        self.username.setEnabled(profile is None)
        self.password.setEnabled(profile is None)
        self.replace.toggled.connect(self.username.setEnabled)
        self.replace.toggled.connect(self.password.setEnabled)
        self.addresses = QPlainTextEdit('\n'.join(profile['addresses']) if profile else '')
        self.addresses.setPlaceholderText('One device IP or address per line.\nExample: 192.0.2.13\nUse https:// or a port if the device requires it.')
        form.addRow('Profile name', self.name)
        form.addRow(self.replace)
        form.addRow('Device username', self.username)
        form.addRow('Device password', self.password)
        form.addRow('Assigned devices', self.addresses)
        note = QLabel('The same credentials are used only for the addresses listed here.\n'
                      'Saving does not change passwords on any device. Saved passwords are never displayed.')
        note.setWordWrap(True)
        form.addRow(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def submit(self):
        try:
            self.store.save_profile(name=self.name.text(), username=self.username.text(),
                password=self.password.text() if self.replace.isChecked() else None,
                addresses=self.addresses.toPlainText().splitlines(), profile_id=self.profile['id'] if self.profile else None)
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        self.password.clear()
        self.accept()


class AdministrationDialog(QDialog):
    def __init__(self, atlas):
        super().__init__(atlas)
        self.atlas, self.store = atlas, atlas.access
        self.setWindowTitle('Administration')
        self.resize(850, 610)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.account_buttons = {}
        for title, callback in [('Create Director Account', self.setup), ('Sign In', self.sign_in),
                                ('Change My Password', self.change_password), ('Connect to Account Server', self.connect_server)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.account_buttons[title] = button
            if title == 'Create Director Account':
                button.setEnabled(not self.store.configured)
        layout.addLayout(actions)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.users = self.table_page('Users', ['Username', 'Role', 'Status', 'Permitted functions'],
                                    [('Create User', lambda: self.edit_user(False)), ('Edit User / Permissions', lambda: self.edit_user(True))])
        self.profiles = self.table_page('Device Credentials', ['Profile', 'Assigned devices'],
                    [('Add Profile', lambda: self.edit_profile(False)), ('Edit Profile', lambda: self.edit_profile(True)),
                     ('Remove Profile', self.remove_profile)])
        self.audit = self.table_page('Audit', ['UTC', 'User', 'Action', 'Target'], [('Refresh', self.refresh)])
        server_page = QWidget()
        form = QFormLayout(server_page)
        self.host = QLineEdit(str(atlas.settings.value('account_bind', '127.0.0.1')))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(atlas.settings.value('account_port', 8443)))
        self.fingerprint = QLineEdit()
        self.fingerprint.setReadOnly(True)
        self.server_status = QLabel()
        self.server_status.setWordWrap(True)
        form.addRow(QLabel('On the hosting computer, sign in as director and start the account server.\n'
            'Choose this computer’s LAN IP for other workstations.\n'
            'The server runs while this Atlas process remains open. Firewall rules are not changed automatically.'))
        form.addRow('Listen on local IP', self.host)
        form.addRow('Port', self.port)
        form.addRow('Certificate SHA-256', self.fingerprint)
        self.server_address = QLineEdit()
        self.server_address.setReadOnly(True)
        form.addRow('Server address for clients', self.server_address)
        self.start_server = QPushButton('Start Account Server')
        self.start_server.clicked.connect(self.start_service)
        form.addRow(self.start_server)
        form.addRow(self.server_status)
        self.tabs.addTab(server_page, 'Account Server')
        layout.addWidget(QLabel('Accounts and permissions apply inside Atlas. Windows account/file access remains a separate security boundary.'))
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def table_page(self, name, headers, buttons):
        page = QWidget()
        layout = QVBoxLayout(page)
        table = QTreeWidget()
        table.setRootIsDecorated(False)
        table.setHeaderLabels(headers)
        layout.addWidget(table)
        row = QHBoxLayout()
        for title, callback in buttons:
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.tabs.addTab(page, name)
        return table

    def refresh(self):
        user = self.store.user
        director = bool(user and user['director'] and not user['must_change'])
        self.status.setText(('Signed in: ' + user['name'] if user else 'Signed out' if self.store.configured else 'Setup mode · no accounts configured') +
            (' · Central account server' if isinstance(self.store, RemoteAccess) else ' · This computer hosts the account database'))
        self.account_buttons['Create Director Account'].setEnabled(not self.store.configured)
        self.account_buttons['Sign In'].setEnabled(self.store.configured and user is None)
        self.account_buttons['Change My Password'].setEnabled(user is not None)
        self.account_buttons['Connect to Account Server'].setEnabled(not self.store.configured or director)
        for index in range(3):
            self.tabs.setTabEnabled(index, director)
        self.tabs.setTabEnabled(3, director and not isinstance(self.store, RemoteAccess))
        for table in (self.users, self.profiles, self.audit):
            table.clear()
        if director:
            try:
                for user in self.store.users():
                    item = QTreeWidgetItem([user['name'], 'Technical Director' if user['director'] else 'Engineer',
                        'Disabled' if not user['enabled'] else 'Password change required' if user['must_change'] else 'Enabled',
                        'All' if user['director'] else ', '.join(PERMISSIONS[k] for k in json.loads(user['permissions']) if k in PERMISSIONS)])
                    item.setData(0, Qt.UserRole, user)
                    for column in range(4):
                        item.setToolTip(column, item.text(column))
                    self.users.addTopLevelItem(item)
                for profile in self.store.profiles():
                    item = QTreeWidgetItem([profile['name'], ', '.join(profile['addresses'])])
                    item.setData(0, Qt.UserRole, profile)
                    self.profiles.addTopLevelItem(item)
                for entry in self.store.audit_rows():
                    self.audit.addTopLevelItem(QTreeWidgetItem([entry[key] for key in ('at', 'actor', 'action', 'target')]))
            except ERRORS as exc:
                self.status.setText(str(exc))
        running = self.atlas.account_server
        self.start_server.setEnabled(director and not running)
        self.host.setEnabled(not running)
        self.port.setEnabled(not running)
        self.fingerprint.setText(running.fingerprint if running else '')
        self.server_address.setText(f'https://{self.host.text().strip()}:{running.port}' if running else '')
        self.server_status.setText(f'Running · port {running.port}. Other workstations need the server LAN IP and fingerprint above.' if running else 'Stopped')
        for column, width in enumerate((150, 140, 180)):
            self.users.setColumnWidth(column, width)

    def setup(self):
        if SignInDialog(self.store, self, setup=True).exec() == QDialog.Accepted:
            self.atlas.apply_permissions()
            self.refresh()

    def sign_in(self):
        if self.store.user:
            return
        self.atlas.sign_in()
        self.refresh()

    def change_password(self):
        if not self.store.user:
            return
        PasswordDialog(self.store, self).exec()
        self.atlas.apply_permissions()

    def edit_user(self, existing):
        try:
            self.store.require_director()
            item = self.users.currentItem()
            user = item.data(0, Qt.UserRole) if existing and item else None
            if existing and (not user or user['director']):
                return
            UserDialog(self.store, self, user).exec()
            self.refresh()
        except ERRORS as exc:
            QMessageBox.warning(self, 'Administration', str(exc))

    def edit_profile(self, existing):
        try:
            self.store.require_director()
            item = self.profiles.currentItem()
            if existing and not item:
                return
            ProfileDialog(self.store, self, item.data(0, Qt.UserRole) if existing else None).exec()
            self.refresh()
        except ERRORS as exc:
            QMessageBox.warning(self, 'Administration', str(exc))

    def remove_profile(self):
        item = self.profiles.currentItem()
        if not item:
            return
        if QMessageBox.question(self, 'Remove Profile', 'Remove this saved profile and its assignments? Device passwords will not change.') != QMessageBox.Yes:
            return
        try:
            self.store.remove_profile(item.data(0, Qt.UserRole)['id'])
            self.refresh()
        except ERRORS as exc:
            QMessageBox.warning(self, 'Administration', str(exc))

    def connect_server(self):
        if self.store.configured and not (self.store.user and self.store.user['director']):
            QMessageBox.information(self, 'Account Server', 'Sign in as technical director to change the account server.')
            return
        if self.atlas.account_server:
            QMessageBox.information(self, 'Account Server', 'This computer is hosting the account server. Connect other workstations instead.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Connect Workstation to Account Server')
        form = QFormLayout(dialog)
        address = QLineEdit(str(self.atlas.settings.value('account_server_url', 'https://')))
        fingerprint = QLineEdit(str(self.atlas.settings.value('account_server_fingerprint', '')))
        fingerprint.setMinimumWidth(480)
        form.addRow(QLabel('Copy the address and SHA-256 fingerprint from the director’s Account Server screen.'))
        form.addRow('Server address', address)
        form.addRow('Certificate SHA-256', fingerprint)
        error = QLabel()
        error.setWordWrap(True)
        form.addRow(error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)
        def connect():
            try:
                remote = RemoteAccess(address.text(), fingerprint.text())
                if SignInDialog(remote, dialog).exec() != QDialog.Accepted:
                    return
                if not self.atlas.end_session():
                    remote.logout()
                    return
                self.atlas.access = self.store = remote
                self.atlas.settings.setValue('account_server_url', address.text().strip())
                self.atlas.settings.setValue('account_server_fingerprint', remote.fingerprint)
                self.atlas.settings.sync()
                self.atlas.apply_permissions()
                dialog.accept()
            except ERRORS as exc:
                error.setText(str(exc))
        buttons.accepted.connect(connect)
        dialog.exec()
        self.refresh()

    def start_service(self):
        try:
            self.store.require_director()
            if isinstance(self.store, RemoteAccess) or self.atlas.account_server:
                return
            server = AccountServer(self.atlas.access_path, self.atlas.data_dir / 'state' / 'account-server', self.host.text().strip(), self.port.value())
            server.start()
            self.atlas.account_server = server
            self.atlas.settings.setValue('account_bind', self.host.text().strip())
            self.atlas.settings.setValue('account_port', server.port)
            self.refresh()
        except ERRORS as exc:
            QMessageBox.warning(self, 'Account Server could not start', str(exc))
