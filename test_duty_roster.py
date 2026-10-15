import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication
from duty_roster import DutyRoster, MOSCOW
from main import Atlas
from duty_panel import DutyPanel


class DutyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setup_store(self,path):
        store=DutyRoster(path)
        store.configure(['Engineer A','Engineer B','Engineer C','Engineer D'],'2026-09-09','08:00')
        return store

    def test_rotation_before_anchor_midnight_and_handover(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.setup_store(Path(d)/'roster.db')
            self.assertEqual(store.duty(date(2026,9,8))['person'],'Engineer D')
            self.assertEqual(store.duty(date(2026,9,10))['person'],'Engineer B')
            for hour,person in [(0,'Engineer A'),(7,'Engineer A'),(8,'Engineer B'),(23,'Engineer B')]:
                self.assertIn(person,store.answer('Кто сейчас на смене?',datetime(2026,9,10,hour,0,tzinfo=MOSCOW)))
            self.assertIn('Engineer C',store.answer('Кто завтра на смене?',datetime(2026,9,10,9,tzinfo=MOSCOW)))
            self.assertIn('Engineer D',store.answer('Кто послезавтра на смене?',datetime(2026,9,10,9,tzinfo=MOSCOW)))
            self.assertIn('Engineer B',DutyRoster(store.path).answer('Кто на смене 2026-09-10?'))

    def test_leave_persistence_overlap_idempotency_and_manual_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.setup_store(Path(d)/'roster.db')
            first=store.add_vacation('Engineer B','2026-09-11','2026-09-13','Director')
            self.assertEqual(first,store.add_vacation('Engineer B','2026-09-11','2026-09-13','Director'))
            self.assertTrue(store.duty(date(2026,9,10))['on_leave']) # shift crosses vacation midnight
            with self.assertRaises(ValueError):store.add_vacation('Engineer B','2026-09-12','2026-09-15','Director')
            store.replace('2026-09-10','Engineer D','Director')
            self.assertEqual(DutyRoster(store.path).duty(date(2026,9,10))['person'],'Engineer D')
            self.assertEqual(store.duty(date(2026,9,11))['scheduled'],'Engineer C')
            with self.assertRaises(ValueError):store.replace('2026-09-10','Engineer B','Director')
            store.cancel_vacation(first,'Director')
            self.assertEqual(store.vacations(),[])
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM audit').fetchone()[0],4)

    def test_gui_vacation_and_question_work_without_model(self):
        with tempfile.TemporaryDirectory() as d:
            window=Atlas(d)
            try:
                window.roster.configure(['Engineer A','Engineer B'],'2026-09-09','08:00')
                panel=DutyPanel(window)
                panel.person.setCurrentText('Engineer B')
                panel.first.setDate(QDate(2026,9,10));panel.last.setDate(QDate(2026,9,12))
                panel.add_leave()
                self.assertEqual(len(DutyRoster(window.roster.path).vacations()),1)
                window.prompt.setPlainText('Кто на смене 2026-09-10?')
                with patch.object(window,'launch_request') as launch:
                    window.send.click()
                launch.assert_not_called()
                self.assertIn('пересекается с отпуском',window.chat.toPlainText())
                with patch.object(window.access,'allowed',return_value=False):
                    panel.person.setCurrentText('Engineer A');panel.add_leave()
                self.assertEqual(len(window.roster.vacations()),1)
            finally:window.close();self.app.processEvents()
