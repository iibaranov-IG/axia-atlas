"""Seal an accepted portable build against a clean committed source tree."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_paths import VERSION


def package(build, acceptance):
    build = build.resolve()
    report = json.loads((acceptance / 'self-test.json').read_text(encoding='utf-8'))
    if not (report.get('passed') and report.get('frozen') and report.get('version') == VERSION):
        raise ValueError('A passing frozen acceptance report for this version is required.')
    with (build / 'AxiaAtlas.exe').open('rb') as executable:
        actual_hash = hashlib.file_digest(executable, 'sha256').hexdigest()
    if report.get('executable_sha256') != actual_hash:
        raise ValueError('The executable differs from the accepted executable.')
    tests = json.loads((ROOT / 'state/isolated-tests/summary.json').read_text(encoding='utf-8'))
    if not tests or any(row['exit_code'] != 0 for row in tests):
        raise ValueError('The source acceptance suite has not passed.')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise ValueError('Commit the reviewed release files before packaging.')
    info = json.loads((build / 'BUILD.json').read_text(encoding='utf-8'))
    for name, expected in info['source_files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Source changed after build: ' + name)
    forbidden = {'station_data.json', 'station-reference.json', 'site_device_groups.json',
                 'inventory.json', 'layout.ini'}
    for path in build.rglob('*'):
        public_ca_bundle = path.relative_to(build).as_posix() == '_internal/certifi/cacert.pem'
        if path.is_file() and (path.name in forbidden or path.suffix in {'.sqlite', '.sqlite3', '.db'}
                              or (path.suffix == '.pem' and not public_ca_bundle)):
            raise ValueError('Workstation data found in distribution: ' + str(path))
    info['build_base_commit'] = info['source_commit']
    info['source_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    info['source_dirty'] = False
    info['source_verified_by_sha256'] = True
    (build / 'BUILD.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    # Copy acceptance metadata, never raw tests' temporary workstation content.
    (build / 'ACCEPTANCE.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    archive = build.parent / ('AxiaAtlas-' + VERSION + '-windows-x64.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(build.rglob('*')):
            if path.is_file():
                output.write(path, Path('AxiaAtlas') / path.relative_to(build))
    with zipfile.ZipFile(archive) as output:
        if output.testzip() is not None:
            raise ValueError('ZIP verification failed')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    archive.with_suffix('.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps(dict(archive=str(archive), sha256=digest, bytes=archive.stat().st_size), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, default=ROOT / 'dist/release-candidate/AxiaAtlas')
    parser.add_argument('--acceptance', type=Path, default=ROOT / 'state/frozen-acceptance')
    args = parser.parse_args()
    package(args.build, args.acceptance)
