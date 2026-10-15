import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from main import Atlas
from equipment import EquipmentStore, LEGACY_FIELDS
from workspace_tools import management_url
from localization import configure, tr
from transcription import as_srt


class WorkspaceToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_localization_catalog_and_saved_language(self):
        base = Path(__file__).parent / 'translations'
        source = json.loads((base / 'source.json').read_text(encoding='utf-8'))
        for code in ('ru', 'en'):
            catalog = json.loads((base / (code + '.json')).read_text(encoding='utf-8'))
            self.assertFalse(set(source) - set(catalog))
            for key in source:
                self.assertEqual(sorted(re.findall(r'\{[^{}]*\}',key)), sorted(re.findall(r'\{[^{}]*\}',catalog[key])), key)
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'layout.ini'), QSettings.IniFormat)
            settings.setValue('interface_language','ru'); settings.sync()
            w = Atlas(folder)
            try:
                self.assertEqual(w.left_tabs.tabText(3), 'Приборы')
                self.assertEqual(w.left_tabs.tabText(4), 'Сценарии')
                self.assertEqual(w.log.origin.itemData(2), 'Devices')
                self.assertEqual(w.log.origin.itemText(2), 'Приборы')
                self.assertEqual(w.open_transcription().run_button.text(), 'Расшифровать')
                self.assertEqual(tr('Backup channel'), 'Резервный канал')
            finally: w.close(); self.app.processEvents(); configure('en')

    def test_devices_has_no_duplicate_network_scanner(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Atlas(folder)
            try:
                w.left_tabs.setCurrentIndex(3)
                w.tabs.setCurrentIndex(3)
                self.assertFalse(hasattr(w.devices_nav, 'scan_button'))
                self.assertEqual(w.left_tabs.tabText(0), tr('Network'))
            finally: w.close();self.app.processEvents()

    def test_saved_management_endpoint_keeps_port(self):
        self.assertEqual(management_url('192.0.2.44:2021', '192.0.2.44'),
                         'http://192.0.2.44:2021/')
        self.assertEqual(management_url('https://192.0.2.45:7777/config', '192.0.2.45'),
                         'https://192.0.2.45:7777/config')

    def test_devices_save_search_reopen_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Atlas(folder)
            try:
                store=w.devices_nav.store
                store.save('192.0.2.10', dict.fromkeys(LEGACY_FIELDS, 'old'), 0, 'test')
                panel=w.open_equipment('192.0.2.10')
                self.assertEqual(panel.fields['studio'].text(),'old')
                panel.fields['name'].setText('Backup codec')
                panel.fields['manufacturer'].setText('Barix')
                panel.fields['model'].setText('Test model')
                panel.save_button.click()
                self.assertEqual(w.devices_nav.items.count(),1)
                w.devices_nav.search.setText('barix')
                self.assertEqual(w.devices_nav.items.count(),1)
                w.devices_nav.items.setCurrentRow(0)
                w.devices_nav.open_card()
                self.assertEqual(w.tabs.currentWidget().fields['name'].text(),'Backup codec')
                self.assertEqual(w.inventory.devices,{})
                self.assertEqual(len(store.history('192.0.2.10')),2)
                with patch.object(w.access,'allowed', return_value=False):
                    w.devices_nav.refresh()
                    self.assertEqual(w.devices_nav.items.count(),0)
            finally: w.close(); self.app.processEvents()

    def test_physical_equipment_card_has_no_invented_ip_or_web_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            w = Atlas(folder)
            try:
                store = w.devices_nav.store
                values = dict.fromkeys(LEGACY_FIELDS, '') | {
                    'name': 'Microphone 05', 'manufacturer': 'Neumann',
                    'model': 'KMS 104', 'category': 'Studio microphone',
                }
                store.save('asset:microphone-05', values, 0, 'test')
                mic = store.get('asset:microphone-05')
                mic['asset_number'] = '5'
                mic['livewire_channel'] = '4027'
                store.save('asset:microphone-05', {key: mic[key] for key in LEGACY_FIELDS + ('name', 'manufacturer', 'model', 'category', 'asset_number', 'livewire_channel')}, mic['revision'], 'test')
                node_values = dict.fromkeys(LEGACY_FIELDS, '') | {
                    'name': 'Main Studio xNode', 'manufacturer': 'Axia',
                    'model': 'Microphone Node', 'category': 'Studio audio I/O node',
                }
                from test_release_fixtures import seed_studio
                seed_studio(w.studio_map)
                store.save('192.0.2.10', node_values, 0, 'test')
                w.devices_nav.refresh()
                self.assertEqual(w.devices_nav.items.count(), 0)
                w.open_equipment('asset:microphone-05')
                self.assertEqual(w.tabs.currentWidget().address, 'asset:microphone-05')
                panel = w.open_equipment('192.0.2.10')
                self.assertIn('Livewire 12345', panel.signal_map.toPlainText())
                self.assertIn('Fixture microphone', panel.signal_map.toPlainText())
            finally: w.close(); self.app.processEvents()

    def test_scenario_workspace_save_and_reopen_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Atlas(folder)
            try:
                panel=w.open_scenarios()
                panel.name.setText('Reserve studio')
                panel.steps=[dict(ip='192.0.2.20',output=1,primary=100,backup=200)]
                panel.save()
                self.assertEqual(w.scenarios_nav.items.count(),1)
                w.scenarios_nav.items.setCurrentRow(0)
                w.scenarios_nav.open()
                self.assertIs(w.tabs.currentWidget(),panel)
                self.assertEqual(panel.steps[0]['backup'],200)
                self.assertFalse(panel.execute.isEnabled())
                self.assertIsNone(panel.job)
            finally: w.close(); self.app.processEvents()

    def test_transcript_save_preserves_original_and_subtitle_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Atlas(folder)
            try:
                p=w.open_transcription()
                p.segments=[dict(start=1.2,end=3.4,text='Hello radio')];p.complete=True
                p.text.setPlainText('Hello radio');p.file.setText(str(Path(folder)/'source.wav'))
                target=Path(folder)/'captions.srt'
                with patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'Subtitles (*.srt)')): p.save()
                self.assertEqual(target.read_text(encoding='utf-8-sig'),as_srt(p.segments))
                self.assertIn('00:00:01,200 --> 00:00:03,400',target.read_text(encoding='utf-8-sig'))
                with patch.object(w.access,'allowed',return_value=False), patch.object(QFileDialog,'getSaveFileName') as dialog:
                    p.save(); dialog.assert_not_called()
            finally: w.close(); self.app.processEvents()

    def test_real_transcription_gui(self):
        root=Path(__file__).parent
        audio=root/'state/transcription-check/speech-ru.wav'
        model=root/'state/speech-model'
        if not audio.is_file() or not (model/'model.bin').is_file(): self.skipTest('Local speech fixture is not installed')
        with tempfile.TemporaryDirectory() as folder:
            w=Atlas(folder)
            try:
                p=w.open_transcription();p.model_dir=model
                with patch.object(QFileDialog,'getOpenFileName',return_value=(str(audio),'Audio')):p.choose.click()
                p.language.setCurrentIndex(p.language.findData('ru'))
                p.run_button.click()
                deadline=time.monotonic()+60
                while p.process is not None and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.02)
                self.assertIsNone(p.process)
                self.assertTrue(p.complete,p.status.text())
                self.assertIn('резервный источник звука',p.text.toPlainText().lower())
                target=Path(folder)/'transcript.txt'
                with patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'Text (*.txt)')):p.save_button.click()
                self.assertIn('Дежурный инженер',target.read_text(encoding='utf-8-sig'))
                (root/'state/transcription-check/gui-result.txt').write_text(p.text.toPlainText(),encoding='utf-8')
                p.start('transcribe');p.cancel.click()
                deadline=time.monotonic()+10
                while p.process is not None and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.02)
                self.assertIsNone(p.process);self.assertFalse(p.complete);self.assertFalse(p.save_button.isEnabled())
            finally: w.close(); self.app.processEvents()
