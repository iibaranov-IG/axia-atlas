"""Run the actual EXE without Python in PATH and bind acceptance to its hash."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def accept(executable, output):
    executable = executable.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with executable.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report_path = output / 'self-test.json'
    # Never allow a stale success from a previous executable to pass.
    report_path.unlink(missing_ok=True)
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    windows = Path(os.environ['SystemRoot'])
    env['PATH'] = str(windows / 'System32') + ';' + str(windows)
    subprocess.run([str(executable), '--self-test', str(output)], cwd=ROOT, env=env,
                   timeout=60, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if not (report.get('passed') and report.get('frozen')):
        raise ValueError('Frozen acceptance failed')
    with executable.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            raise ValueError('Executable changed during acceptance')
    report['executable_sha256'] = digest
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, default=ROOT / 'dist/release-candidate/AxiaAtlas/AxiaAtlas.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'state/frozen-acceptance')
    args = parser.parse_args()
    accept(args.executable, args.output)
