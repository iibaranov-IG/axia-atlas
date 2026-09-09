import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from network_tree import NetworkTree, OrderedItem, KIND
from PySide6.QtCore import Qt


class TreeTests(unittest.TestCase):
    def test_confirmed_telephony_group_survives_device_refresh(self):
        app = QApplication.instance() or QApplication([])
        tree = NetworkTree()
        overrides = {f'192.0.2.{i}': {'group': 'Telephony'} for i in (127, 128, 129)}
        with patch.dict('network_tree.SITE_GROUPS', overrides, clear=True):
            for address in overrides:
                tree.ensure_device(f'http://{address}/', {'ip': address})
            tree.ensure_device('http://192.0.2.127/', {'ip': '192.0.2.127', 'device_type': 'VX Engine'})
            tree.set_grouped(False)
            tree.set_grouped(True)
        app.processEvents()
        self.assertEqual(tree.groups['Telephony'].childCount(), 3)
        self.assertEqual(len(tree.devices()), 3)
        self.assertNotIn('Awaiting Identification', tree.groups)
        tree.close()

    def test_grouping_numeric_order_filter_and_single_expanded_device(self):
        app = QApplication.instance() or QApplication([])
        tree = NetworkTree()
        tree.show()
        high = tree.ensure_device('http://192.0.2.100/', {'ip': '192.0.2.100', 'device_type': 'LiveMic'})
        low = tree.ensure_device('http://192.0.2.9/', {'ip': '192.0.2.9', 'device_type': 'LiveMic'})
        high.addChild(OrderedItem(['3101 · Studio mic', 'Enabled']))
        low.addChild(OrderedItem(['1301 · News mic', 'Enabled']))
        app.processEvents()
        self.assertEqual(tree.topLevelItemCount(), 1)
        self.assertIs(tree.topLevelItem(0).child(0), low)
        high.setExpanded(True)
        low.setExpanded(True)
        self.assertFalse(high.isExpanded())
        tree.filter('1301')
        self.assertTrue(high.isHidden())
        self.assertFalse(low.isHidden())
        tree.set_grouped(False)
        self.assertEqual(tree.topLevelItemCount(), 2)
        self.assertEqual(len(tree.devices()), 2)
        tree.filter('')
        tree.set_grouped(True)
        tree.ensure_device('http://192.0.2.9/', {'ip': '192.0.2.9', 'device_type': 'lwwd'})
        self.assertEqual(tree.topLevelItemCount(), 2)
        self.assertEqual(len(tree.devices()), 2)
        self.assertEqual(low.parent().text(0), 'PC Audio Drivers')
        tree.close()
