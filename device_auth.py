"""Device authentication with one attempt per explicitly assigned credential profile."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox


def request_credentials(parent, url, realm):
    dialog = QDialog(parent)
    dialog.setWindowTitle('Device Sign In')
    form = QFormLayout(dialog)
    message = QLabel(f'Device: {url.host()}\nAccess area: {realm}\n'
        'Enter the device credentials. If this window appears again, the device rejected the previous sign-in.')
    message.setTextFormat(Qt.PlainText)
    message.setWordWrap(True)
    form.addRow(message)
    username = QLineEdit()
    username.setObjectName('device_username')
    password = QLineEdit()
    password.setObjectName('device_password')
    password.setEchoMode(QLineEdit.Password)
    form.addRow('Username', username)
    form.addRow('Password', password)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    username.setFocus()
    result = (username.text(), password.text()) if dialog.exec() == QDialog.Accepted else None
    password.clear()
    dialog.deleteLater()
    return result


def authenticate(parent, url, authenticator):
    if parent.property('auth_cancelled'):
        QTimer.singleShot(0, parent.stop)
        return
    access_provider = getattr(parent, '_atlas_access', None)
    if access_provider:
        store = access_provider()
        if not store.allowed('device_ui'):
            parent.setProperty('auth_cancelled', True)
            QTimer.singleShot(0, parent.stop)
            return
        base = QUrl()
        base.setScheme(url.scheme())
        base.setHost(url.host())
        base.setPort(url.port(443 if url.scheme() == 'https' else 80))
        address = base.toString()
        attempts = getattr(parent, '_atlas_auth_attempts', set())
        # No retry loop with a rejected saved password. Redirected hosts receive
        # credentials only if separately assigned by the technical director.
        if address not in attempts:
            attempts.add(address)
            parent._atlas_auth_attempts = attempts
            try:
                saved = store.credentials(address)
            except (OSError, ValueError, PermissionError) as exc:
                parent.setProperty('auth_cancelled', True)
                QTimer.singleShot(0, parent.stop)
                QMessageBox.warning(parent, 'Device Sign In', str(exc))
                return
            if saved is not None:
                authenticator.setUser(saved[0])
                authenticator.setPassword(saved[1])
                return
    credentials = request_credentials(parent, url, authenticator.realm())
    if credentials is not None:
        authenticator.setUser(credentials[0])
        authenticator.setPassword(credentials[1])
    else:
        parent.setProperty('auth_cancelled', True)
        QTimer.singleShot(0, parent.stop)
