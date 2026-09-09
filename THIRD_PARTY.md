# Third-party software and source references

The MIT license covers original Atlas code. It does not replace dependency licenses or grant rights to vendor manuals, firmware or trademarks. Bundled dependency notices are in `third_party_notices/`; installed versions are recorded in its `versions.json`.

Atlas uses unmodified upstream binary packages. PySide/Qt libraries are supplied as separate files in the portable `_internal` directory. They are not statically linked into Atlas. Users may replace these libraries with compatible modified versions or rebuild Atlas from source. Atlas imposes no additional restriction on debugging modifications to LGPL-covered components. Keep dependency notices when redistributing.

| Component | Upstream source and build information |
|---|---|
| Python 3.11.9 | https://www.python.org/downloads/release/python-3119/ |
| PySide6 / Shiboken 6.8.3 | https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.8.3 |
| Qt 6.8.3 including WebEngine/PDF | https://download.qt.io/archive/qt/6.8/6.8.3/submodules/ |
| Qt build instructions | https://doc.qt.io/qt-6.8/build-sources.html |
| Qt for Python build instructions | https://doc.qt.io/qtforpython-6.8/building_from_source/index.html |
| NumPy 2.2.6 | https://github.com/numpy/numpy/tree/v2.2.6 |
| python-soxr 0.5.0.post1 and libsoxr | https://pypi.org/project/soxr/0.5.0.post1/#files |
| lameenc 1.8.4 and bundled LAME | https://github.com/chrisstaite/lameenc/tree/v1.8.4 |
| cryptography 50.0.1 and OpenSSL | https://pypi.org/project/cryptography/50.0.1/#files |
| cffi 2.1.1 | https://pypi.org/project/cffi/2.1.1/#files |
| pycparser 3.0 | https://pypi.org/project/pycparser/3.0/#files |
| PyInstaller bootloader 6.22.2 | https://pyinstaller.org/en/stable/license.html |

PySide/Qt is used under its applicable open-source LGPL terms. Qt WebEngine includes Chromium and other separately licensed components; Qt Multimedia includes FFmpeg components. Consult the included upstream Qt module licensing pages for component-specific notices and source references. These components are not licensed solely under Atlas's MIT license.

Official licensing references: https://doc.qt.io/qt-6.8/licensing.html and https://doc.qt.io/qt-6.8/qtwebengine-licensing.html.

The Qt documentation URLs track the 6.8 series and may describe a later patch release. They are licensing references, not an exact binary manifest. The binary package versions are recorded separately; `bundled-chromium-credits.html` is exported from the actual installed Qt WebEngine. Cryptography's bundled OpenSSL reports version 4.0.2; its source is https://github.com/openssl/openssl/tree/openssl-4.0.2 and its license is included. The lameenc build recipe above fetches LAME 3.100, applies its documented patch and contains the instructions for rebuilding the replaceable extension.

The application's original protocol implementation was informed by the Telos Livewire Routing Protocol documentation and independent discovery observations published at https://github.com/nick-prater/read_lw_sources. Atlas is an independent project, without a claim of official certification or endorsement.
