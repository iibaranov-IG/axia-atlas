import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPdfWriter,QPainter
from manual_knowledge import ManualKnowledge,grounded_response
from manual_panel import ManualPanel
from document_viewer import DocumentViewer
from main import Atlas


class ManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def fixture(self,folder):
        path=Path(folder)/'fixture.pdf'
        writer=QPdfWriter(str(path));painter=QPainter(writer)
        painter.drawText(100,100,'General introduction for the engineering reference document.')
        writer.newPage();painter.drawText(100,100,'Microphone phantom power: +48 VDC, switchable. Test reference only.')
        painter.end();del writer
        entry=dict(title='Test xNode reference',family='xNode (original generation)',url='https://example.test/manual.pdf',source_page='https://example.test',applicability='Synthetic test only')
        return path,entry

    def test_index_idempotency_provenance_family_and_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            store=ManualKnowledge(Path(d)/'index');path,entry=self.fixture(d)
            first=store.ingest(path,entry);self.assertEqual(store.ingest(path,entry),first)
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM passages').fetchone()[0],2)
            rows=store.search('xNode фантомное питание')
            self.assertEqual(rows[0]['page'],2);self.assertEqual(rows[0]['path'],str(path.resolve()))
            self.assertEqual(store.search('phantom','Omnia ONE'),[])
            self.assertEqual(store.search('неизвестно'),[])
            self.assertEqual(store.context('192.0.2.1 phantom'),[])
            self.assertTrue(store.context('192.0.2.1 phantom',devices=[dict(ip='192.0.2.1',device_type='axiaxnode.mic4')]))
            self.assertLessEqual(len('\n'.join(text for _,text in store.context('phantom')).encode()),3202)
            evidence=store.context('phantom')
            for answer in ['中文 [M1]','Wrong reference [M9]','No source']:
                self.assertIn('Надёжного пересказа не получилось',grounded_response(answer,evidence))
            self.assertIn('требует сверки',grounded_response('Power [M1]',evidence))

    def test_gui_search_open_page_and_assistant_context_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            window=Atlas(d)
            try:
                path,entry=self.fixture(d);window.manuals.ingest(path,entry)
                window.open_manuals();panel=window.tabs.currentWidget();self.assertIsInstance(panel,ManualPanel)
                panel.query.setText('xNode фантомное питание');panel.search();panel.open_item();self.app.processEvents()
                viewer=window.tabs.currentWidget();self.assertIsInstance(viewer,DocumentViewer)
                self.assertEqual(viewer.pdf.pageCount(),2);self.assertEqual(viewer.page_number.value(),2)
                window.assistant_model='test';window.prompt.setPlainText('xNode фантомное питание')
                with patch.object(window,'launch_request') as launch:window.ask()
                self.assertIn('Microphone phantom power',launch.call_args.args[0].prompt)
                window.prompt.setPlainText('xNode фантомное питание')
                original=window.access.allowed
                with patch.object(window.access,'allowed',side_effect=lambda p:p!='library' and original(p)):
                    with patch.object(window,'launch_request') as launch:window.ask()
                self.assertNotIn('Manufacturer manual',launch.call_args.args[0].prompt)
            finally:window.close();self.app.processEvents()
