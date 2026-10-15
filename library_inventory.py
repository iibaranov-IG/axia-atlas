"""Explicit model-to-reference matching; never treats an unknown model as compatible."""
from equipment import is_network_card
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
        matches = [d for d in devices if entry['family'] in families(d)
                   and (not d.get('manual_reference') or entry['kind'] == 'Manuals')]
        if matches:
            types = '|'.join(sorted({d.get('device_type', '').casefold() for d in matches}))
            found = ', '.join(sorted(d['ip'] for d in matches))
            result.append(dict(entry, detected_types=types, notes=entry['notes'] + '\nEquipment: ' + found + ('\nIncludes manually entered model; verify against the device label.' if any(d.get('manual_reference') for d in matches) else '')))
    return result


def inventory_note(devices):
    unknown = [d['ip'] for d in devices if not families(d)]
    return (f'{len(devices)} discovered / saved devices. Resources follow identified equipment. '
            + ('No verified model match: ' + ', '.join(sorted(unknown)) if unknown else '')) if devices else 'No equipment discovered yet. Start Network Scan to populate the library.'


def reference_devices(discovered, cards):
    """Keep observations intact; exact manual model names only add manual references."""
    result = [dict(device) for device in discovered]
    known = {device['ip'] for device in result if families(device)}
    aliases = {'xnode': 'xnode', 'xnode2': 'xnode2', 'quasar': 'quasar',
               'qor': 'qor', 'omnia one': 'omnia-one', 'vx engine': 'vx engine',
               'axia ip audio driver': 'lwwd', 'ip audio driver': 'lwwd'}
    for card in cards:
        # Physical assets (microphones, speakers, racks) do not advertise on
        # the network and must not be represented as discovered devices.
        if not is_network_card(card['ip']):
            continue
        if card['ip'] in known: continue
        model = card.get('model', '').strip().casefold()
        manufacturer = card.get('manufacturer', '').strip().casefold()
        kind = aliases.get(model, '') if manufacturer in ('axia', 'telos', 'telos alliance', 'omnia') else ''
        result = [d for d in result if d['ip'] != card['ip']]
        result.append(dict(ip=card['ip'], device_type=kind, manual_reference=True))
    return result
