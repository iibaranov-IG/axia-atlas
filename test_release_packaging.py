"""A valid ZIP must also be extractable by ordinary Windows file tools."""
import tempfile
import unittest
from pathlib import Path

from tooling.package_release import check_portable_paths


class PortablePathTests(unittest.TestCase):
    def test_rejects_a_library_asset_that_exceeds_windows_destination_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            build = Path(folder)
            asset = build / '_internal' / ('a' * 85 + '.png')
            asset.parent.mkdir()
            asset.write_bytes(b'fixture')
            check_portable_paths(build, destination_characters=100)
            with self.assertRaisesRegex(ValueError, 'too long'):
                check_portable_paths(build, destination_characters=160)

    def test_accepts_unicode_and_spaces_in_normal_portable_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            build = Path(folder)
            (build / 'AxiaAtlas.exe').write_bytes(b'fixture')
            (build / 'Инструкция по работе.txt').write_text('Проверка', encoding='utf-8')
            check_portable_paths(build)
