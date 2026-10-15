"""Run desktop test modules in independent Qt processes, preserving every failure."""
import json
import re
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
output=root/'state'/'isolated-tests';output.mkdir(parents=True,exist_ok=True)
results=[]
for path in sorted(root.glob('test_*.py')):
    run=subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',path.stem,'-q'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=180)
    (output/(path.stem+'.txt')).write_text(run.stdout,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests?',run.stdout)
    results.append(dict(module=path.stem,exit_code=run.returncode,tests=int(count[1]) if count else 0))
    print(path.stem,run.returncode,flush=True)
(output/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('TOTAL',sum(r['tests'] for r in results),'PASSED',all(r['exit_code']==0 for r in results),flush=True)
sys.exit(0 if all(r['exit_code']==0 for r in results) else 1)
