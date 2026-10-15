"""Explicit maintainer import of manufacturer-linked manuals for a saved inventory."""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse
from manual_sources import sources_for
from manual_knowledge import ManualKnowledge

HOSTS={'www.telosalliance.com','telosalliance-uat.s3.amazonaws.com','telosalliance-uat.s3.us-east-1.amazonaws.com'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inventory',required=True)
    parser.add_argument('--folder',required=True)
    args=parser.parse_args()
    folder=Path(args.folder);folder.mkdir(parents=True,exist_ok=True)
    inventory=json.loads(Path(args.inventory).read_text(encoding='utf-8'))['devices']
    store=ManualKnowledge(folder)
    results=[]
    for entry in sources_for(list(inventory.values())):
        try:
            if urlparse(entry['url']).hostname not in HOSTS:raise ValueError('Unexpected document source')
            with urlopen(Request(entry['url'],headers={'User-Agent':'AxiaAtlas documentation import'}),timeout=40) as response:
                if urlparse(response.url).hostname not in HOSTS:raise ValueError('Unexpected redirect')
                content=response.read(40*1024*1024+1)
                final=response.url
            if len(content)>40*1024*1024 or not content.startswith(b'%PDF-'):raise ValueError('Not a supported PDF')
            digest=hashlib.sha256(content).hexdigest()
            path=folder/(digest+'.pdf')
            if not path.exists():path.write_bytes(content)
            provenance=dict(entry,sha256=digest,downloaded_at=datetime.now(timezone.utc).isoformat(),final_url=final)
            report=path.with_suffix('.json')
            if not report.exists():report.write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
            doc_id=store.ingest(path,entry)
            result=dict(title=entry['title'],family=entry['family'],status='indexed',id=doc_id)
        except Exception as exc:result=dict(title=entry['title'],status='failed',error=str(exc))
        results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    (folder/'import-report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'documents':len(store.documents()),'results':results},ensure_ascii=False))

if __name__=='__main__':main()
