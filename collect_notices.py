"""Collect installed dependency notices plus upstream Qt/GNU licensing texts.

Run in the pinned build environment. Network failure fails the collection.
"""
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
PACKAGES = ('PySide6', 'PySide6_Addons', 'PySide6_Essentials', 'shiboken6',
            'numpy', 'soxr', 'lameenc', 'cryptography', 'cffi', 'pycparser')

def collect():
    target = ROOT / 'third_party_notices'
    target.mkdir(exist_ok=True)
    versions = {'Python': sys.version.split()[0]}
    for name in PACKAGES:
        dist = metadata.distribution(name)
        versions[name] = dist.version
        for item in dist.files or []:
            if any(word in str(item).lower() for word in ('license', 'copying', 'notice')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    destination = target / name / Path(str(item))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', target / 'Python-LICENSE.txt')
    urls = {
        'LGPL-3.0.txt': 'https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/LGPL-3.0-only.txt',
        'GPL-3.0.txt': 'https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/GPL-3.0-only.txt',
        'LGPL-2.1.txt': 'https://raw.githubusercontent.com/spdx/license-list-data/main/text/LGPL-2.1-only.txt',
        'PyInstaller-COPYING.txt': 'https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.22.2/COPYING.txt',
        'OpenSSL-LICENSE.txt': 'https://raw.githubusercontent.com/openssl/openssl/openssl-4.0.2/LICENSE.txt',
    }
    urls['qt-licensing.html'] = 'https://doc.qt.io/qt-6.8/licensing.html'
    urls['qtmultimedia-index.html'] = 'https://doc.qt.io/qt-6.8/qtmultimedia-index.html'
    for module in ('qtpdf', 'qtwebengine'):
        urls[f'{module}-licensing.html'] = f'https://doc.qt.io/qt-6.8/{module}-licensing.html'
    for name, url in urls.items():
        print('Collecting', name, flush=True)
        request = urllib.request.Request(url, headers={'User-Agent': 'AxiaAtlas-build/0.1'})
        with urllib.request.urlopen(request, timeout=60) as response:
            (target / name).write_bytes(response.read())
    (target / 'versions.json').write_text(json.dumps(versions, indent=2), encoding='utf-8')
    (target / 'notice-origins.json').write_text(json.dumps(urls, indent=2), encoding='utf-8')
    # Capture credits from the actual bundled Chromium version, rather than
    # treating the rolling Qt documentation site as an exact component manifest.
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView
    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()
    loop = QEventLoop()
    view.loadFinished.connect(loop.quit)
    QTimer.singleShot(15000, loop.quit)
    view.load(QUrl('chrome://credits/'))
    loop.exec()
    result = []
    def ready(html):
        result.append(html)
        loop.quit()
    view.page().toHtml(ready)
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    if not result or len(result[0]) < 10000:
        raise RuntimeError('Could not export bundled Chromium credits')
    (target / 'bundled-chromium-credits.html').write_text(result[0], encoding='utf-8')
    view.close()
    app.processEvents()

if __name__ == '__main__':
    collect()
