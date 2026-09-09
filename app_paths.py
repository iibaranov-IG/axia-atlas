"""Writable state stays outside the frozen application's installation directory."""
import os
from pathlib import Path
import sys

VERSION = '0.1.0-preview.1'


def application_data_dir():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'AxiaAtlas'
    return Path(__file__).parent
