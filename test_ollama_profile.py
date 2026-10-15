import io
import json
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from main import Atlas, OllamaRequest
from ollama_profile import MODEL, SYSTEM, PARAMETERS, system_for_language


class OllamaProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_request_uses_explicit_system_and_limits(self):
        self.assertIn('Всегда отвечай на русском языке', SYSTEM)
        self.assertIn('Не запрашивай пароли', SYSTEM)
        response = {'message': {'content': 'Insufficient evidence'}, 'done': True}
        received = []
        job = OllamaRequest(MODEL, 'Synthetic question')
        job.result.connect(received.append)
        with patch('main.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            job.run()
            req = factory.return_value.open.call_args.args[0]
            payload = json.loads(req.data)
        self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(payload['messages'][0]['content'], SYSTEM)
        self.assertEqual(payload['options'], PARAMETERS)
        self.assertNotIn('tools', payload)
        self.assertEqual(received, [response])

    def test_answer_language_persists_and_request_snapshots_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                self.assertEqual(window.answer_language.currentData(), 'ru')
                window.answer_language.setCurrentIndex(window.answer_language.findData('en'))
                window.assistant_model = MODEL
                window.prompt.setPlainText('Explain monitoring')
                with patch.object(window, 'launch_request') as launch:
                    window.ask()
                job = launch.call_args.args[0]
                self.assertEqual(job.system, system_for_language('en'))
                self.assertIn('Always answer in clear professional English', job.system)
                self.assertNotIn('Всегда отвечай на русском', job.system)
                self.assertIn('Не запрашивай пароли', job.system)
                window.answer_language.setCurrentIndex(0)
                self.assertEqual(job.system, system_for_language('en'))
                window.answer_language.setCurrentIndex(1)
            finally:
                window.close(); self.app.processEvents()
            reopened = Atlas(directory)
            try: self.assertEqual(reopened.answer_language.currentData(), 'en')
            finally: reopened.close(); self.app.processEvents()

    def test_fixed_profile_missing_profile_and_oversize_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Atlas(directory)
            try:
                response = {'models': [{'name': 'other:7b'}, {'name': MODEL},
                    {'name': 'remote', 'remote_host': 'https://example.invalid'}]}
                window.models_received(response)
                self.assertEqual(window.assistant_model, MODEL)
                self.assertFalse(hasattr(window, 'models'))
                window.settings.setValue('assistant/model', 'other:7b')
                window.models_received(response)
                self.assertEqual(window.assistant_model, MODEL)
                window.models_received({'models': [{'name': 'other:7b'}]})
                self.assertEqual(window.assistant_model, '')
                self.assertTrue(window.send.isEnabled())
                from localization import tr
                self.assertEqual(tr('Виртуальный инженер не настроен. Обратитесь к администратору.'), window.connection.text())
                window.models_received(response)
                window.pending_context = 'x' * 6001
                window.prompt.setPlainText('Question')
                with patch.object(window, 'launch_request') as launch:
                    window.ask()
                launch.assert_not_called()
                self.assertEqual(window.prompt.toPlainText(), 'Question')
                self.assertEqual(len(window.pending_context), 6001)
            finally:
                window.close()
                self.app.processEvents()
