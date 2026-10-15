import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from station_knowledge import StationKnowledge
from main import Atlas
from test_release_fixtures import station_fixture

class StationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_city_conflict_preserves_origin_and_dated_correction(self):
        with tempfile.TemporaryDirectory() as folder:
            station = StationKnowledge(station_fixture(Path(folder) / 'reference.json'))
            answer = station.answer('Какая частота в Тестограде?')
            for expected in ('99,2', '99,1', 'РАСХОЖДЕНИЕ', '2026-01-02', 'https://example.test/old'):
                self.assertIn(expected, answer)
            for question in ('Почему пропадают потоки Livewire?', 'Частота дискретизации xNode', 'Кто на смене?', 'Как проверить потери RTP?'):
                self.assertIsNone(station.answer(question))
                self.assertEqual(station.context(question), '')

    def test_new_workstation_has_no_station_or_studio_records(self):
        with tempfile.TemporaryDirectory() as folder:
            window = Atlas(folder)
            try:
                self.assertIsNone(window.station.data)
                self.assertEqual(window.studio_map.topology_rows(), [])
                self.assertEqual(window.inventory.devices, {})
                self.assertFalse(window.discovery_active)
                self.assertEqual(window.left_tabs.tabText(0), 'Сеть')
            finally:
                window.close()
                self.app.processEvents()

    def test_gui_reference_and_existing_records_survive_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            station_fixture(Path(folder) / 'state/station-reference.json')
            window = Atlas(folder)
            try:
                window.open_station()
                panel = window.tabs.currentWidget()
                panel.kind.setCurrentIndex(1)
                panel.query.setText('Тестоград')
                self.assertEqual(panel.table.topLevelItemCount(), 1)
                window.prompt.setPlainText('Какая частота в Тестограде?')
                with patch.object(window, 'launch_request') as launch:
                    window.ask()
                launch.assert_not_called()
                self.assertIn('99,2', window.chat.toPlainText())
                window.settings.setValue('interface_language', 'en')
            finally:
                window.close()
                self.app.processEvents()
            reopened = Atlas(folder)
            try:
                self.assertEqual(reopened.left_tabs.tabText(0), 'Network')
                self.assertIn('99,2', reopened.station.answer('Частота в Тестограде?'))
            finally:
                reopened.close()
                self.app.processEvents()
