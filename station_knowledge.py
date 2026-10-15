"""Read-only station reference. Frequencies never pass through a language model."""
import json
import re
from pathlib import Path


def normalize(text):
    return re.sub(r'[^а-яa-z0-9]+',' ',text.casefold().replace('ё','е')).strip()


class StationKnowledge:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(__file__).with_name('station_data.json')
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else None

    def city_matches(self,question):
        if not self.data:return []
        q=normalize(question)
        aliases={'Москва':['москв'],'Санкт-Петербург':['петербург','спб','питер'],
                 'Ростов-на-Дону':['ростов'],'Петропавловск-Камчатский':['петропавловск'],
                 'Нижний Новгород':['нижн новгород']}
        found=[]
        for row in self.data['cities']:
            words=normalize(row['city']).split()
            stems=[re.sub(r'(ий|ая|а|я|ь|и|о)$','',w) if len(w)>3 else w for w in words]
            variants=aliases.get(row['city'],[])
            match=all(re.search(r'\b'+re.escape(s)+r'\w*\b',q) for s in stems)
            match=match or any(all(re.search(r'\b'+re.escape(s)+r'\w*\b',q) for s in v.split()) for v in variants)
            if match:found.append(row)
        return found

    def city_text(self,row):
        correction=row.get('engineer_correction')
        if correction:
            lines=[row['city']+' — '+correction['frequency_mhz'].replace('.',',')+' МГц FM',
                   'Уточнение инженера от '+correction['received_at']+'. Независимая проверка приёма не проводилась.',
                   'РАСХОЖДЕНИЕ с опубликованными источниками; прежние сведения сайта сохранены ниже:']
        else:
            lines=[row['city']+(' — РАСХОЖДЕНИЕ ИСТОЧНИКОВ, требуется уточнение' if row['conflict'] else '')]
        for observation in row['observations']:
            value=(observation['frequency_mhz'].replace('.',',')+' МГц FM') if observation['frequency_mhz'] else observation['mode']
            lines.append(value+' — '+observation['source_url'])
        return '\n'.join(lines)

    def satellite_text(self,row):
        labels={'spacecraft':'КА','package':'Пакет','band':'Диапазон','format':'Стандарт','polarization':'Поляризация',
                'transponder':'Транспондер','frequency_mhz':'Частота, МГц','modulation':'Модуляция','fec':'FEC',
                'symbol_rate_msps':'Символьная скорость, Msym/s','sid':'SID','apid':'APID','note':'Примечание'}
        parts=[row['name'],row['status']]
        if row['conflicting_fields']:parts.append('РАСХОЖДЕНИЕ: '+', '.join(labels.get(k,k) for k in row['conflicting_fields']))
        for o in row['observations']:
            parts.append('\nИсточник: '+o.get('source_url',o.get('source_label',''))+(' · действует с '+o['effective_from'] if o.get('effective_from') else ''))
            parts.append('; '.join(labels.get(k,k)+': '+str(v) for k,v in o['parameters'].items() if k!='name' and v is not None and v!=''))
        return '\n'.join(parts)

    def summary(self):
        s=self.data['station']
        return s['summary']+'\nСайт: '+s['website']+'\nИсточник: '+s['source_url']+'\n\n'+s['coverage_claim']+'\n'+s['coverage_source']

    def answer(self,question):
        q=normalize(question)
        if re.search(r'смен|дежур|отпуск',q):return None
        apps=bool(re.search(r'приложен|логотип|лого |android|андроид|pcradio|radiocent|mytuner',q))
        digital=bool(re.search(r'подкаст|площадк|tunein|itunes|youtube',q))
        station=bool(re.search(r'радио\s*кп|radiokp|комсомольск\w*\s+правд|наш\w* радиостанц',q))
        digital = digital or (station and bool(re.search(r'онлайн|поток', q)))
        satellite=bool(re.search(r'спутник|ямал|abs|нтв|триколор|транспондер',q))
        frequency=bool(re.search(r'частот|\bfm\b|мгц|веща',q))
        if not self.data:return 'Справочник Радио КП не установлен.' if station else None
        matched=self.city_matches(q) if frequency or station else []
        if not (station or satellite or matched or apps or digital or 'города вещания' in q):return None
        stamp='Сведения источников проверены '+self.data['checked_at']+'. Приём в эфире не измерялся.\n\n'
        if apps:
            rows=self.data.get('apps',[])
            if re.search(r'логотип|лого',q):rows=[r for r in rows if r['note']]
            elif re.search(r'\bнет\b|отсутств',q):rows=[r for r in rows if r['reported_status']=='нет']
            elif 'проверить' in q:rows=[r for r in rows if r['reported_status']=='проверить']
            return 'По таблице инженера, полученной 10.09.2026; дата проверки приложений неизвестна. Отметки не подтверждены повторным тестом.\n\n'+'\n\n'.join(self.app_text(r) for r in rows)
        if digital:
            rows=self.data.get('digital',[])
            if 'подкаст' in q:rows=[r for r in rows if r['category']=='Подкасты']
            elif 'поток' in q:rows=[r for r in rows if r['category']=='Поток']
            return 'Площадки Радио КП. Статус указан отдельно для каждой ссылки.\n\n'+'\n\n'.join(self.digital_text(r) for r in rows)
        if satellite:
            chosen=self.data['satellites']
            if 'триколор' in q:chosen=[r for r in chosen if 'Триколор' in r['name']]
            elif 'нтв' in q:chosen=[r for r in chosen if 'НТВ' in r['name']]
            elif 'ямал' in q:chosen=[r for r in chosen if 'Ямал' in r['name']]
            elif 'abs' in q:chosen=[r for r in chosen if 'ABS' in r['name']]
            for token in ('запад','сибир','восток'):
                if token in q:chosen=[r for r in chosen if token in r['name'].casefold()]
            return stamp+'\n\n'.join(self.satellite_text(r) for r in chosen)
        if matched:return stamp+'\n\n'.join(self.city_text(r) for r in matched)
        if re.search(r'города|городах|список|где вещает|где вещаем|сколько город',q):
            rows=self.data['cities'];fm=sum(any(o['mode']=='FM' for o in r['observations']) for r in rows)
            return stamp+f'В опубликованных списках найдено {len(rows)} городских записей, из них {fm} с FM-частотами. Это не полный перечень населённых пунктов в зоне покрытия.\n\n'+'\n\n'.join(self.city_text(r) for r in rows)
        if frequency:return stamp+'Для указанного запроса нет однозначной записи. Укажите город из справочника. Отсутствие города в списке не доказывает отсутствие вещания.'
        return stamp+self.summary()

    def app_text(self,row):
        return f"{row['name']} ({row['package_id']}) — отметка: {row['reported_status']}"+(' · '+row['note'] if row['note'] else '')+'\n'+row['url']+'\n'+row['verification']

    def digital_text(self,row):
        return f"{row['category']} · {row['name']}\n{row['url']}\n{row['status']}\nИсточник: "+row.get('source_url','Таблица инженера')

    def context(self,question,budget=3000):
        if not self.data or self.answer(question) is None:return ''
        q=normalize(question)
        blocks=['Station reference; snapshot '+self.data['checked_at']+'. '+self.summary()]
        cities=self.city_matches(question)
        blocks.extend(self.city_text(r) for r in cities[:3])
        if re.search(r'спутник|ямал|abs|нтв|триколор',q):
            satellites=self.data['satellites']
            for token in ('ямал','abs','нтв','триколор','запад','сибир','восток'):
                if token in q:satellites=[r for r in satellites if token in r['name'].casefold()]
            for r in satellites[:2]:
                blocks.append(r['name']+' — '+r['status']+'; conflicting fields: '+', '.join(r['conflicting_fields']))
                observations=sorted(r['observations'],key=lambda o:0 if o['source_kind']=='operator' else 1)
                blocks.extend(json.dumps(o,ensure_ascii=False) for o in observations)
        if re.search(r'приложен|логотип|лого|android|андроид',q):
            rows=self.data.get('apps',[])
            if re.search(r'логотип|лого',q):rows=[r for r in rows if r['note']]
            elif re.search(r'\bнет\b|отсутств',q):rows=[r for r in rows if r['reported_status']=='нет']
            blocks.extend(self.app_text(r) for r in rows[:5])
        if re.search(r'подкаст|онлайн|площадк|поток',q):
            rows=[r for r in self.data.get('digital',[]) if r['source_kind']=='website']
            if 'подкаст' in q:rows=[r for r in rows if r['category']=='Подкасты']
            blocks.extend(self.digital_text(r) for r in rows[:4])
        result=[]
        for block in blocks:
            if len(('\n\n'.join(result+[block])).encode('utf-8'))<=budget:result.append(block)
        return '\n\n'.join(result)
