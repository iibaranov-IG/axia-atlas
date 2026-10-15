"""Build the independent Windows player using the current project's Python."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir',
        '--name', 'AtlasBroadcastPlayer', '--distpath', str(args.dist_dir.resolve()),
        '--workpath', str(ROOT / 'build' / 'player'), '--specpath', str(ROOT / 'build'),
        '--add-data', str(ROOT / 'LICENSE') + ';.',
        '--add-data', str(ROOT / 'BROADCAST_PLAYER.md') + ';.',
        '--exclude-module', 'PySide6.QtWebEngineCore', '--exclude-module', 'PySide6.QtWebEngineWidgets',
        '--exclude-module', 'torch', '--exclude-module', 'faster_whisper',
        str(ROOT / 'run_broadcast_player.py'),
    ], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
