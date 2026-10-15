"""Local duty calendar: explicit rotation, dated leave and manual replacements.

No employee data is embedded in source, no model is used for calendar arithmetic.
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MOSCOW = timezone(timedelta(hours=3), 'Europe/Moscow')


class DutyRoster:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS configuration (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS leave (id INTEGER PRIMARY KEY, person TEXT NOT NULL,
                    first TEXT NOT NULL, last TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS replacements (day TEXT PRIMARY KEY, person TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, time TEXT NOT NULL,
                    actor TEXT NOT NULL, action TEXT NOT NULL, body TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def log(self, db, actor, action, body):
        db.execute('INSERT INTO audit(time,actor,action,body) VALUES (?,?,?,?)',
                   (datetime.now(MOSCOW).isoformat(), actor, action, json.dumps(body, ensure_ascii=False)))

    def config(self):
        with self.connection() as db:
            row = db.execute('SELECT body FROM configuration WHERE id=1').fetchone()
        return json.loads(row['body']) if row else None

    def configure(self, cycle, anchor, handover=None, actor='User', expected=None):
        cycle = [name.strip() for name in cycle]
        if not cycle or any(not name or len(name)>120 for name in cycle) or len(set(cycle)) != len(cycle):
            raise ValueError('Enter distinct, non-empty staff names.')
        date.fromisoformat(anchor)
        if handover is not None and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', handover):
            raise ValueError('Handover time must be HH:MM.')
        record = {'cycle': cycle, 'anchor': anchor, 'handover': handover, 'timezone': 'Europe/Moscow'}
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM configuration WHERE id=1').fetchone()
            old = json.loads(row['body']) if row else None
            if old != expected:
                raise ValueError('The rotation changed. Reload before saving.')
            db.execute('INSERT OR REPLACE INTO configuration VALUES (1,?)', (json.dumps(record,ensure_ascii=False),))
            self.log(db, actor, 'rotation', {'before': old, 'after': record})

    def vacations(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM leave WHERE active=1 ORDER BY first,person')]

    def add_vacation(self, person, first, last, actor):
        start, end = date.fromisoformat(first), date.fromisoformat(last)
        cfg = self.config()
        if not cfg or person not in cfg['cycle'] or end < start:
            raise ValueError('Select a staff member and a valid inclusive date range.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            exact = db.execute('SELECT id FROM leave WHERE active=1 AND person=? AND first=? AND last=?',
                               (person,first,last)).fetchone()
            if exact:
                return exact['id']
            if db.execute('SELECT 1 FROM leave WHERE active=1 AND person=? AND first<=? AND last>=?',
                          (person,last,first)).fetchone():
                raise ValueError('This vacation overlaps an existing entry. Review its dates first.')
            cursor = db.execute('INSERT INTO leave(person,first,last) VALUES (?,?,?)', (person,first,last))
            self.log(db,actor,'vacation added',{'person':person,'first':first,'last':last})
            return cursor.lastrowid

    def cancel_vacation(self, entry_id, actor):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM leave WHERE id=? AND active=1',(entry_id,)).fetchone()
            if row:
                db.execute('UPDATE leave SET active=0 WHERE id=?',(entry_id,))
                self.log(db,actor,'vacation cancelled',dict(row))

    def replace(self, day, person, actor):
        date.fromisoformat(day)
        cfg=self.config()
        if not cfg or person not in cfg['cycle']:
            raise ValueError('Select a known staff member.')
        shift_last=(date.fromisoformat(day)+timedelta(days=1)).isoformat() if cfg['handover'] not in (None,'00:00') else day
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM leave WHERE active=1 AND person=? AND first<=? AND last>=?',(person,shift_last,day)).fetchone():
                raise ValueError('This staff member is on vacation that day.')
            db.execute('INSERT OR REPLACE INTO replacements VALUES (?,?)',(day,person))
            self.log(db,actor,'replacement assigned',{'day':day,'person':person})

    def duty(self, day):
        cfg = self.config()
        if not cfg:
            return None
        scheduled = cfg['cycle'][(day-date.fromisoformat(cfg['anchor'])).days % len(cfg['cycle'])]
        shift_last=day+timedelta(days=1) if cfg['handover'] not in (None,'00:00') else day
        with self.connection() as db:
            row=db.execute('SELECT person FROM replacements WHERE day=?',(day.isoformat(),)).fetchone()
            person=row['person'] if row else scheduled
            leave=db.execute('SELECT 1 FROM leave WHERE active=1 AND person=? AND first<=? AND last>=?',
                             (person,shift_last.isoformat(),day.isoformat())).fetchone()
        return {'day':day.isoformat(),'scheduled':scheduled,'person':person,'on_leave':bool(leave),'replacement':bool(row)}

    def answer(self, question, now=None):
        text=question.casefold().replace('ё','е')
        if not (re.search(r'(кто|дежур|смен|отпуск)', text)):
            return None
        if 'отпуск' in text:
            if 'кто' in text:
                target=(now or datetime.now(MOSCOW)).astimezone(MOSCOW).date()
                if 'послезавтра' in text:target+=timedelta(days=2)
                elif 'завтра' in text:target+=timedelta(days=1)
                elif 'вчера' in text:target-=timedelta(days=1)
                exact=re.search(r'\b\d{4}-\d{2}-\d{2}\b',text)
                if exact:
                    try:target=date.fromisoformat(exact.group())
                    except ValueError:return 'Указана неверная дата отпуска.'
                today=target.isoformat()
                people=[entry['person'] for entry in self.vacations() if entry['first']<=today<=entry['last']]
                return 'По сохранённым отпускам на '+today+': '+(', '.join(people) if people else 'записей об отпуске нет')+'.'
            return 'Отпуска сохраняются в календаре смен: укажите сотрудника и даты начала и окончания. Замена назначается отдельно.'
        if not (('кто' in text or 'дежур' in text) and ('смен' in text or 'дежур' in text)):
            return None
        cfg=self.config()
        if not cfg:
            return 'График смен ещё не задан. Откройте календарь смен.'
        now=now or datetime.now(MOSCOW)
        if now.tzinfo is None:
            raise ValueError('A timezone-aware clock is required.')
        local=now.astimezone(MOSCOW)
        target=local.date()
        exact=re.search(r'\b\d{4}-\d{2}-\d{2}\b',text)
        if exact:
            try: target=date.fromisoformat(exact.group())
            except ValueError: return 'Указана неверная дата. Используйте ГГГГ-ММ-ДД.'
        elif 'послезавтра' in text or 'через день' in text: target+=timedelta(days=2)
        elif 'завтра' in text: target+=timedelta(days=1)
        elif 'вчера' in text: target-=timedelta(days=1)
        elif 'сегодня' not in text and cfg['handover']:
            hour,minute=map(int,cfg['handover'].split(':'))
            if (local.hour,local.minute)<(hour,minute): target-=timedelta(days=1)
        entry=self.duty(target)
        if entry['on_leave']:
            answer=f"На {target:%d.%m.%Y} назначен {entry['person']}, но смена пересекается с отпуском. Нужна замена; доступный дежурный не подтверждён."
        else:
            answer=f"По графику на {target:%d.%m.%Y} — {entry['person']}."
            if entry['replacement']: answer+=f" Назначенная замена вместо {entry['scheduled']}."
        if cfg['handover']:
            answer+=f" Передача смены в {cfg['handover']} по Москве."
        else:
            answer+=' Время передачи смены ещё не задано; это ответ по календарной дате, не подтверждение присутствия.'
        return answer
