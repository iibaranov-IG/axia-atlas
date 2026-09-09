import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from resources import ResourceLibrary, ResourceNavigator, CATALOG
from PySide6.QtCore import Qt


class ResourceTests(unittest.TestCase):
    def test_categories_and_family_do_not_mix_resources(self):
        app = QApplication.instance() or QApplication([])
        navigator = ResourceNavigator()
        page = ResourceLibrary()
        for kind in ('Manuals', 'Firmware', 'Software'):
            navigator.kind.setCurrentText(kind)
            for i in range(navigator.tree.topLevelItemCount()):
                root = navigator.tree.topLevelItem(i)
                for j in range(root.childCount()):
                    child = root.child(j)
                    if not root.isHidden() and not child.isHidden():
                        entry = child.data(0, Qt.UserRole)
                        self.assertEqual(entry['kind'], kind)
                        page.kind.setCurrentText(kind)
                        page.family.setCurrentText(entry['family'])
                        visible = [page.table.topLevelItem(n).data(0, Qt.UserRole)
                            for n in range(page.table.topLevelItemCount())
                            if not page.table.topLevelItem(n).isHidden()]
                        self.assertIn(entry, visible)
                        self.assertTrue(all(v['kind'] == kind and v['family'] == entry['family'] for v in visible))
        navigator.close()
        page.close()

    def test_filter_selection_and_official_link(self):
        app = QApplication.instance() or QApplication([])
        page = ResourceLibrary()
        page.show()
        page.kind.setCurrentText('Software')
        visible = [page.table.topLevelItem(i) for i in range(page.table.topLevelItemCount())
                   if not page.table.topLevelItem(i).isHidden()]
        self.assertEqual(len(visible), 1)
        page.table.setCurrentItem(visible[0])
        self.assertIn('64-bit', page.details.text())
        requested = []
        page.open_requested.connect(lambda url, title: requested.append((url, title)))
        with patch('resources.QDesktopServices.openUrl', return_value=True) as opened:
            page.open_page()
            opened.assert_not_called()
            self.assertEqual(requested[0][0].host(), 'docs.telosalliance.com')
        page.search.setText('not-a-real-model')
        self.assertFalse(page.open_button.isEnabled())
        self.assertTrue(all(page.table.topLevelItem(i).isHidden() for i in range(page.table.topLevelItemCount())))
        page.close()
        app.processEvents()

    def test_families_and_release_labels_are_explicit(self):
        legacy = [entry for entry in CATALOG if entry['kind'] == 'Firmware' and 'Legacy Analog' in entry['family']][0]
        self.assertIn('Beta', legacy['version'])
        self.assertIn('Not for xNode', legacy['notes'])


if __name__ == '__main__':
    unittest.main()
