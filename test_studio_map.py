import tempfile
import unittest
from pathlib import Path
from studio_map import StudioMapStore
from test_release_fixtures import seed_studio

class StudioMapTests(unittest.TestCase):
    def test_explicit_routes_persist_without_guessing_from_channel_number(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'studio-map.sqlite3'
            store = StudioMapStore(path)
            seed_studio(store)
            seed_studio(store)
            reopened = StudioMapStore(path)
            route = reopened.routes_for_node('node:test')[0]
            self.assertEqual(route['livewire_channel'], '12345')
            self.assertEqual(route['node_stream'], 27)
            self.assertEqual(route['origin'], 'Test fixture')
            self.assertEqual(len(reopened.topology_rows()), 2)
            self.assertEqual(reopened.connections_for(asset_number='5')[0]['channel'], '12345')
            self.assertIn('Fixture microphone', reopened.summary())
            self.assertTrue(any(r['target_input'] == 'output 4' for r in reopened.connections_for(ip='192.0.2.10')))

    def test_route_rejects_non_numeric_channel_or_zero_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StudioMapStore(Path(folder) / 'studio-map.sqlite3')
            for channel, stream in [('forty', 27), ('4027', 0)]:
                with self.assertRaises(ValueError):
                    store.add_signal(channel, source_asset_id='mic:test', node_asset_id='node:test', node_stream=stream, purpose='test')
