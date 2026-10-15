"""One per-user state location for both source and packaged Atlas launches."""
import os
from pathlib import Path

VERSION = '0.2.0-rc.1'


def application_data_dir():
    # A source launch is still a real Atlas session.  Keeping it beside the
    # code created a second, empty workstation database and made saved device
    # cards appear to disappear when switching between preview and package.
    # Tests pass their own data_dir to Atlas, so they remain isolated.
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'AxiaAtlas'
