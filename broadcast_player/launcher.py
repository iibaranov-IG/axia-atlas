"""Launch the module in a separate process, including from the Atlas frozen build."""
import sys
from pathlib import Path
from PySide6.QtCore import QProcess


def launch():
    executable = Path(sys.executable)
    if getattr(sys, 'frozen', False):
        return QProcess.startDetached(str(executable), ['--broadcast-player'])
    pythonw = executable.with_name('pythonw.exe')
    if pythonw.exists():
        executable = pythonw
    return QProcess.startDetached(str(executable), ['-m', 'broadcast_player'],
                                  str(Path(__file__).resolve().parent.parent))
