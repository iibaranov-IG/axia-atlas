"""Explicit model-to-reference matching; never treats an unknown model as compatible."""
LEGACY = 'Legacy Analog / AES / Microphone / GPIO Nodes'
DRIVER = 'Axia IP Audio Driver for Windows'


def families(device):
    kind = (device.get('device_type') or '').casefold()
    if kind.startswith('axiaxnode2') or kind == 'xnode2':
        return {'xNode2'}
    if kind.startswith('axiaxnode.') or kind == 'xnode':
        return {'xNode (original generation)', 'xNode / xSwitch / xSelector'}
    return {
        'liveio': {LEGACY}, 'livemic': {LEGACY}, 'liveaes': {LEGACY}, 'livegpio': {LEGACY},
        'livert': {'Router Selector Node (legacy)'}, 'lwwd': {DRIVER},
        'quasar': {'Quasar console / engine'}, 'qengine': {'Quasar console / engine'},
        'qor': {'QOR / iQ'}, 'omnia-one': {'Omnia ONE'}, 'vx engine': {'Telos VX'},
    }.get(kind, set())


def catalog_for(catalog, devices):
    result = []
    for entry in catalog:
        matches = [d for d in devices if entry['family'] in families(d)]
        if matches:
            types = '|'.join(sorted({d.get('device_type', '').casefold() for d in matches}))
            found = ', '.join(sorted(d['ip'] for d in matches))
            result.append(dict(entry, detected_types=types, notes=entry['notes'] + '\nDetected equipment: ' + found))
    return result


def inventory_note(devices):
    unknown = [d['ip'] for d in devices if not families(d)]
    return (f'{len(devices)} discovered / saved devices. Resources follow identified equipment. '
            + ('No verified model match: ' + ', '.join(sorted(unknown)) if unknown else '')) if devices else 'No equipment discovered yet. Start Network Scan to populate the library.'
