import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from main import Atlas
from library_inventory import reference_devices, catalog_for
from resources import CATALOG

class CoreStabilizationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_manual_card_references_preserve_discovery_and_exclude_firmware(self):
  observed=[dict(ip='192.0.2.1',device_type='unknown')]
  card=dict(ip='192.0.2.1',manufacturer='Axia',model='xNode')
  combined=reference_devices(observed,[card])
  self.assertEqual(observed[0]['device_type'],'unknown')
  entries=catalog_for(CATALOG,combined)
  self.assertTrue(entries)
  self.assertTrue(all(e['kind']=='Manuals' for e in entries))
  self.assertEqual(catalog_for(CATALOG,reference_devices([], [dict(card,manufacturer='Barix')])),[])
 def test_scenario_draft_reopens_and_is_not_published_plan(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Atlas(folder)
   p=w.open_scenarios()
   p.name.setText('Unfinished reserve')
   p.steps=[dict(ip='192.0.2.5',output=1,primary=100,backup=101)];p.render()
   self.assertEqual(p.store.plans(),[])
   w.close_tab(w.tabs.indexOf(p));self.app.processEvents()
   p=w.open_scenarios()
   self.assertEqual(p.name.text(),'Unfinished reserve')
   self.assertEqual(p.steps[0]['backup'],101)
   self.assertFalse(p.execute.isEnabled())
   p.save()
   self.assertEqual(w.scenarios_home.items.count(),1)
   self.assertEqual(w.scenarios_nav.items.count(),1)
   w.close();self.app.processEvents()
