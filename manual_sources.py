"""Manufacturer-linked PDF references, reviewed 2026-09-10. No firmware compatibility claim."""
from library_downloads import files_for
from library_inventory import catalog_for
from resources import CATALOG

EXTRA = [
 ('Axia IP Audio Driver for Windows','Using Windows Driver GPIO — January 2007 (legacy reference)',
  'https://telosalliance-uat.s3.amazonaws.com/public/Axia%20Products/IP%20Audio%20Driver/Support%20Files/Using_Windows_Driver_GPIO.pdf',
  'https://www.telosalliance.com/consoles-audio-mixing/accessories/axia-livewire-aes67-ip-audio-driver'),
 ('Axia IP Audio Driver for Windows','Axia Windows Firewall Configuration — October 2006 (legacy reference)',
  'https://telosalliance-uat.s3.amazonaws.com/public/Axia%20Products/IP%20Audio%20Driver/Support%20Files/Axia_Firewall_Config.pdf',
  'https://www.telosalliance.com/consoles-audio-mixing/accessories/axia-livewire-aes67-ip-audio-driver'),
 ('Axia IP Audio Driver for Windows','Axia IP Audio Driver manual — revision 2.10',
  'https://telosalliance-uat.s3.amazonaws.com/public/Axia%20Products/IP%20Audio%20Driver/Support%20Files/Axia_IP_Audio_Driver_Software_Interface.pdf',
  'https://www.telosalliance.com/consoles-audio-mixing/accessories/axia-livewire-aes67-ip-audio-driver'),
 ('Omnia ONE','Omnia ONE All Styles manual — v2.7',
  'https://telosalliance-uat.s3.amazonaws.com/public/Omnia%20Products/Omnia%20ONE/OmniaONE_All_Styles_v2.7.pdf',
  'https://www.telosalliance.com/legacy/omnia-one'),
 ('Telos VX','Telos VX original system user manual — C18217027',
  'https://telosalliance-uat.s3.amazonaws.com/public/Telos%20Products/VX/Support%20Files/Telos_VX_Multi_Studio_IP_Phone_Interface_System_C18217027.pdf',
  'https://www.telosalliance.com/legacy/telos-vx'),
 ('Telos VSet','Telos VSet Broadcast Phones manual — C20417006',
  'https://telosalliance-uat.s3.amazonaws.com/public/Telos%20Products/VSet/Telos_VSet_Manual_C20417006.pdf',
  'https://www.telosalliance.com/broadcast-phone-systems/telos-vset-phone'),
]


def sources_for(devices):
    entries=catalog_for(CATALOG,devices)
    found={entry['family'] for entry in entries}
    result=[]
    for entry in entries:
        if entry['kind']=='Manuals':
            for f in files_for(entry):
                if entry['family']=='Quasar console / engine':
                    f=dict(f,url='https://telosalliance-uat.s3.us-east-1.amazonaws.com/public/Axia+Products/Quasar/Assets/1490-00224-004+Quasar+User+Manual+v3.2.0.2_public-1.pdf',label='Quasar User Manual v3.2.0.2',source_page='https://www.telosalliance.com/consoles-audio-mixing/broadcast-consoles/axia-quasar-soft')
                elif entry['family']=='QOR / iQ':
                    f=dict(f,url='https://telosalliance-uat.s3.amazonaws.com/public/Axia%20Products/iQ/Axia-iQ%20Manual-v1.3.1-C21316028.pdf',source_page='https://www.telosalliance.com/consoles-audio-mixing/broadcast-consoles/axia-iq-family/axia-iq')
                result.append(dict(f,title=f['label'],family=entry['family'],
                    applicability='Family reference; verify hardware and software revision.'))
    for family,title,url,source_page in EXTRA:
        provisional=family=='Telos VSet' and any('vset' in d.get('name','').casefold() for d in devices)
        if family in found or provisional:
            result.append(dict(family=family,title=title,url=url,source_page=source_page,
                applicability='Name-based VSet reference only; model not independently confirmed.' if provisional else
                'Family reference; verify hardware and software revision.'))
    return list({entry['url']:entry for entry in result}.values())
