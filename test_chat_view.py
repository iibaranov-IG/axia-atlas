import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from chat_view import ChatView


class ChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_alignment_plain_text_resize_and_clear(self):
        chat=ChatView();chat.resize(420,500);chat.show()
        try:
            chat.appendPlainText('You: Кто сейчас на смене?')
            chat.appendPlainText('Виртуальный инженер: По графику — Engineer A. Передача в 08:00.')
            chat.appendPlainText('Assistant: <script>not markup</script>\n'+'Long plain text '*35)
            self.app.processEvents()
            user=chat.rows[0][1];assistant=chat.rows[1][1]
            self.assertGreater(user.x(),assistant.x())
            self.assertEqual(chat.rows[2][2].textFormat(),Qt.PlainText)
            self.assertIn('<script>',chat.toPlainText())
            chat.resize(260,450);self.app.processEvents()
            self.assertLess(user.width(),chat.viewport().width())
            chat.clear();self.app.processEvents()
            self.assertEqual(chat.toPlainText(),'')
            self.assertEqual(chat.rows,[])
        finally:chat.close();self.app.processEvents()
