"""Explicit UI translations. Engineering records and device web pages are unchanged."""
import json
from pathlib import Path

LANGUAGES = {'en': 'English', 'ru': 'Русский'}
_language = 'en'
_catalog = {}
_qt_translator = None


def configure(language):
    global _language, _catalog, _qt_translator
    _language = language if language in LANGUAGES else 'en'
    path = Path(__file__).with_name('translations') / (_language + '.json')
    _catalog = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    from PySide6.QtCore import QCoreApplication, QTranslator, QLibraryInfo
    app = QCoreApplication.instance()
    if app:
        if _qt_translator: app.removeTranslator(_qt_translator)
        _qt_translator = QTranslator(app)
        if _qt_translator.load('qtbase_' + _language, QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(_qt_translator)


def tr(text, **values):
    result = _catalog.get(text, text)
    return result.format(**values) if values else result


def language():
    return _language
