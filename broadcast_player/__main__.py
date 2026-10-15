"""Standalone entry point; no Atlas network discovery or assistant initialization."""
import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from .window import PlayerWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description='ATLAS Broadcast Player')
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args(argv)
    data_dir = args.data_dir or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'AtlasBroadcastPlayer')
    data_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('ATLAS Broadcast Player')
    app.setOrganizationName('Atlas')
    lock = QLockFile(str(data_dir / 'player.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, 'ATLAS Broadcast Player', 'Плеер уже открыт с этой медиатекой.\nPlayer is already open with this library.')
        return 0
    try:
        window = PlayerWindow(data_dir)
    except Exception as exc:
        QMessageBox.critical(None, 'ATLAS Broadcast Player', 'Не удалось открыть медиатеку.\nCannot open library.\n\n' + str(exc))
        return 1
    window.show()
    result = app.exec()
    lock.unlock()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
