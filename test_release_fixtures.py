"""Synthetic examples; never read a workstation's engineering records in tests."""
import json

def seed_studio(store):
    store.add_asset('node:test', kind='node', name='Fixture Node', ip='192.0.2.10', role='Synthetic I/O', origin='Test fixture')
    store.add_asset('mic:test', kind='microphone', name='Fixture microphone', axia_number='5', role='Synthetic input', origin='Test fixture')
    store.add_asset('monitor:test', kind='monitor', name='Fixture monitor', role='Synthetic output', origin='Test fixture')
    store.add_signal('12345', source_asset_id='mic:test', node_asset_id='node:test', node_stream=27, purpose='explicit channel exception', origin='Test fixture')
    store.add_direct_route(source_asset_id='node:test', target_asset_id='monitor:test', connection_type='analog', target_input='output 4', purpose='Synthetic monitor', origin='Test fixture')

def station_fixture(path):
    data = dict(schema=1, checked_at='2026-01-01',
        station=dict(name='Fixture radio', summary='Synthetic reference for tests only.',
                     website='https://example.test', source_url='https://example.test/about',
                     coverage_claim='Synthetic coverage', coverage_source='https://example.test/coverage'),
        cities=[dict(city='Тестоград', conflict=True,
            observations=[dict(frequency_mhz='99.1', mode='FM', source_url='https://example.test/old')],
            engineer_correction=dict(frequency_mhz='99.2', received_at='2026-01-02'))],
        satellites=[], apps=[], digital=[])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path
