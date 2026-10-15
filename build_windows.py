"""Build the reviewed source into an isolated portable Windows candidate."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from app_paths import VERSION

ROOT = Path(__file__).resolve().parent

def build():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist-dir', type=Path, default=ROOT/'dist'/'release-candidate')
    args = parser.parse_args()
    target = args.dist_dir.resolve() / 'AxiaAtlas'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onedir', '--windowed', '--noupx', '--name', 'AxiaAtlas',
               '--distpath', str(args.dist_dir.resolve()),
               '--workpath', str(ROOT/'build'/'release-candidate'),
               '--specpath', str(ROOT/'build'),
               '--add-data', str(ROOT/'translations') + ';translations']
    for package in ('soxr', 'lameenc', 'faster_whisper', 'ctranslate2', 'tokenizers'):
        command += ['--collect-all', package]
    subprocess.run(command + [str(ROOT/'main.py')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'collect_notices.py')], cwd=ROOT, check=True)
    for name in ('LICENSE', 'QUICKSTART.md', 'QUICKSTART.ru.md', 'ADMINISTRATION.md',
                 'RELEASE_NOTES.md', 'THIRD_PARTY.md', 'BROADCAST_PLAYER.md'):
        shutil.copy2(ROOT/name, target/name)
    shutil.copytree(ROOT/'third_party_notices', target/'third_party_notices', dirs_exist_ok=True)
    paths = list(ROOT.glob('*.py')) + list((ROOT/'broadcast_player').glob('*.py')) + list((ROOT/'translations').glob('*.json'))
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths)}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    build_info = dict(version=VERSION, source_commit=commit, source_dirty=dirty,
                      python=sys.version, source_files=manifest)
    (target/'BUILD.json').write_text(json.dumps(build_info, indent=2), encoding='utf-8')
    print('Candidate built:', target, flush=True)
    print('Run AxiaAtlas.exe --self-test in a separate directory before packaging.', flush=True)

if __name__ == '__main__':
    build()
