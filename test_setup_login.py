import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from access_control import AccessStore
from main import Atlas

class SetupLoginTests(unittest.TestCase):
 def test_local_only_and_restore(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)
   store=AccessStore(path/'state/accounts.sqlite3');store.setup('director','test-password-123');store.logout()
   before=tuple(store.db.execute('select name,digest,permissions from users').fetchone())
   settings=QSettings(str(path/'layout.ini'),QSettings.IniFormat)
   settings.setValue('local_setup_without_login',True);settings.sync()
   w=Atlas(folder);app.processEvents()
   try:
    self.assertEqual(w.access.user['name'],'Local setup')
    self.assertTrue(w.access.allowed('audio'))
    self.assertFalse(store.allowed('audio'))
    with self.assertRaises(PermissionError):w.access.require_director()
    with patch.object(w,'sign_in') as login:w.restore_sign_in()
    login.assert_called_once()
    self.assertIsNone(w.access.user)
    self.assertFalse(w.access.allowed('audio'))
    self.assertFalse(w.settings.value('local_setup_without_login',True,type=bool))
    self.assertEqual(tuple(store.db.execute('select name,digest,permissions from users').fetchone()),before)
   finally:w.close();app.processEvents();store.db.close()
