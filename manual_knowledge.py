"""Versioned local PDF knowledge with page provenance and bounded lexical retrieval."""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ALIASES = {'фантом':'phantom','питан':'power','микроф':'microphone','канал':'channel',
 'источник':'source','назначен':'destination','вход':'input','выход':'output',
 'усилен':'gain','уров':'level','синхрон':'clock','потер':'loss','пакет':'packet',
 'задерж':'latency','маршрут':'routing','резерв':'backup','прошив':'firmware',
 'телефон':'phone','громк':'volume','приоритет':'priority','мультикаст':'multicast'}
STOP={'what','does','how','the','for','and','with','this','that','from','can','you','manual',
      'как','что','где','это','для','его','мне','надо','можно','расскажи','пожалуйста','руководство','мануал'}


class ManualKnowledge:
    def __init__(self,folder):
        self.folder=Path(folder)
        self.folder.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY, title TEXT, family TEXT, path TEXT, source_url TEXT,
                source_page TEXT, sha256 TEXT, page_count INTEGER, applicability TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    doc UNINDEXED,page UNINDEXED,body,tokenize='unicode61');''')

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.folder/'manuals.sqlite3',timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def ingest(self,path,entry):
        from pypdf import PdfReader
        path=Path(path).resolve()
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        doc_id=hashlib.sha256((entry['url']+digest).encode()).hexdigest()[:24]
        with self.connection() as db:
            if db.execute('SELECT 1 FROM documents WHERE id=?',(doc_id,)).fetchone():return doc_id
        reader=PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('PDF requires a password and cannot be indexed automatically')
        rows=[]
        for number,page in enumerate(reader.pages,1):
            text=re.sub(r'\s+',' ',page.extract_text() or '').strip()
            for start in range(0,len(text),850):
                chunk=text[max(0,start-100):start+850]
                if len(chunk.strip())>30:rows.append((doc_id,number,chunk))
        if not rows:raise ValueError('No searchable text; scanned document requires OCR')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM documents WHERE id=?',(doc_id,)).fetchone():return doc_id
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)',
                (doc_id,entry['title'],entry['family'],str(path),entry['url'],entry['source_page'],digest,len(reader.pages),entry['applicability']))
            db.executemany('INSERT INTO passages(doc,page,body) VALUES (?,?,?)',rows)
        return doc_id

    def documents(self):
        with self.connection() as db:return [dict(row) for row in db.execute('SELECT * FROM documents ORDER BY family,title')]

    def search(self,query,family=None,limit=4):
        if family is None:
            family=self.family_for(query)
        tokens=re.findall(r'[\w]+',query.casefold())
        terms=[]
        for token in tokens:
            if token in STOP or len(token)<3:continue
            if family and token in {'xnode','quasar','qor','omnia','vset','driver','драйвер','routerselector'}:continue
            mapped=next((english for stem,english in ALIASES.items() if token.startswith(stem)),None)
            if mapped:terms.append(mapped)
            elif token.isascii():terms.append(token)
        terms=list(dict.fromkeys(terms))[:16]
        if not terms:return []
        with self.connection() as db:
            rows=[]
            for operator in (' AND ',' OR '):
                expression=operator.join('"'+term.replace('"','')+'"' for term in terms)
                rows=db.execute('''SELECT d.*,p.page,p.body,bm25(passages) AS rank FROM passages p
                    JOIN documents d ON p.doc=d.id WHERE passages MATCH ?
                    AND (? IS NULL OR d.family=?) AND p.body NOT LIKE '%........%'
                    ORDER BY rank LIMIT ?''',
                    (expression,family,family,min(max(limit,1),20))).fetchall()
                if rows:break
        return [dict(row) for row in rows]

    def family_for(self,query):
        q=query.casefold()
        names=[('2960','Cisco Catalyst 2960 / 2960-S'),('xnode','xNode (original generation)'),('quasar','Quasar console / engine'),
               ('qor','QOR / iQ'),('omnia','Omnia ONE'),('vset','Telos VSet'),
               ('vx','Telos VX'),('driver','Axia IP Audio Driver for Windows'),
               ('драйвер','Axia IP Audio Driver for Windows'),('routerselector','Router Selector Node (legacy)')]
        found={family for name,family in names if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',q)}
        return next(iter(found)) if len(found)==1 else None

    def context(self,question,family=None,devices=()):
        addresses=set(re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',question))
        if addresses:
            from library_inventory import families
            available={d['family'] for d in self.documents()}
            matched=[d for d in devices if d.get('ip') in addresses]
            found=set().union(*(families(d) & available for d in matched)) if matched else set()
            if len(matched)!=len(addresses) or len(found)!=1:return []
            family=next(iter(found))
        rows=self.search(question,family,limit=3)
        selected=[]
        budget=3200
        for i,row in enumerate(rows,1):
            header=f"[M{i}] {row['title']}; PDF page {row['page']}; {row['applicability']}\n"
            remaining=budget-len(header.encode('utf-8'))
            if remaining<100:break
            body=row['body'].encode('utf-8')[:min(750,remaining)].decode('utf-8','ignore')
            selected.append((row,header+body))
            budget-=len((header+body).encode('utf-8'))
        return selected


def grounded_response(answer,evidence):
    """Format model prose as unverified; deterministic evidence survives model failure."""
    if not evidence:return answer
    ids={int(value) for value in re.findall(r'\[M(\d+)\]',answer)}
    usable=bool(answer.strip() and ids and ids <= set(range(1,len(evidence)+1)) and not re.search(r'[\u3400-\u9fff]',answer))
    excerpts='\n\n'.join(text for _,text in evidence)
    if not usable:
        return ('Надёжного пересказа не получилось. Ниже — найденные выдержки из руководств на языке оригинала. '
                'Они описывают семейство оборудования; текущие настройки приборов ими не подтверждаются.\n\n'+excerpts)
    return ('Пояснение модели — требует сверки с источниками:\n'+answer+
            '\n\nИсходные выдержки для проверки:\n'+excerpts)
