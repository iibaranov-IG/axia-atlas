"""Build the portable distribution using the active Python environment."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

if __name__ == '__main__':
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--onedir', '--windowed', '--name', 'AxiaAtlas',
                    '--collect-all', 'soxr', '--collect-all', 'lameenc',
                    '--distpath', 'dist', '--workpath', 'build/pyinstaller',
                    '--specpath', 'build', 'main.py'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'collect_notices.py'], cwd=ROOT, check=True)
    target = ROOT / 'dist' / 'AxiaAtlas'
    for name in ('LICENSE', 'QUICKSTART.md', 'ADMINISTRATION.md', 'THIRD_PARTY.md'):
        shutil.copy2(ROOT / name, target / name)
    shutil.copytree(ROOT / 'third_party_notices', target / 'third_party_notices', dirs_exist_ok=True)
    print('Portable build ready in dist/AxiaAtlas. Run its explicit --self-test before release.')
