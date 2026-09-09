"""Local recording history and playback; audio and original reports stay untouched."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTreeWidget, QTreeWidgetItem, QPushButton, QFileDialog, QSlider)


class RecordingsPanel(QWidget):
    playback_requested = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.paths = list(dict.fromkeys(settings.value('recording_history', [], type=list)))
        self.media = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(.15)
        self.media.setAudioOutput(self.output)
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        heading.addWidget(QLabel('Recorded files'), 1)
        self.add_button = QPushButton('Add Files…')
        self.add_button.clicked.connect(self.choose_files)
        heading.addWidget(self.add_button)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh)
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(['Recording / Channel', 'Recorded', 'Duration', 'Format', 'Audio quality'])
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 155)
        self.table.setColumnWidth(4, 220)
        self.table.currentItemChanged.connect(self.selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.play_selected())
        layout.addWidget(self.table, 1)
        self.status = QLabel('Select a recording. Files are played locally; live monitoring stops when playback starts.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.play_button = QPushButton('Play Recording')
        self.play_button.clicked.connect(self.play_selected)
        self.stop_button = QPushButton('Stop Recording Playback')
        self.stop_button.clicked.connect(self.media.stop)
        self.folder_button = QPushButton('Open Folder')
        self.folder_button.clicked.connect(self.open_folder)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(15)
        self.volume.valueChanged.connect(lambda value: self.output.setVolume(value / 100))
        for widget in (self.play_button, self.stop_button, self.folder_button, QLabel('Volume'), self.volume):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.media.errorOccurred.connect(lambda _, message: self.status.setText(f'Cannot play recording: {message}'))
        self.media.mediaStatusChanged.connect(self.media_status)
        self.media.playbackStateChanged.connect(self.playback_state)
        self.refresh()

    def add_file(self, path):
        path = str(Path(path).resolve())
        if Path(path).suffix.lower() not in ('.wav', '.mp3'):
            return
        if path not in self.paths:
            self.paths.insert(0, path)
            self.settings.setValue('recording_history', self.paths)
        self.refresh()
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i)
            if item.data(0, Qt.UserRole) == path:
                self.table.setCurrentItem(item)
                break

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add Recordings',
            self.settings.value('recording_folder', ''), 'Audio recordings (*.wav *.mp3)')
        for path in paths:
            self.add_file(path)

    def refresh(self):
        current = self.selected_path()
        self.table.clear()
        for value in self.paths:
            path = Path(value)
            report = {}
            report_error = False
            try:
                report_path = Path(value + '.json')
                if report_path.exists():
                    report = json.loads(report_path.read_text(encoding='utf-8'))
                    if not isinstance(report, dict):
                        raise ValueError('Invalid recording report')
            except (OSError, ValueError):
                report = {}
                report_error = True
            source = report.get('source', {})
            if not isinstance(source, dict):
                source = {}
            title = f'{source.get("channel", "—")} · {source.get("name", path.name)}'
            try:
                duration = max(0, float(report.get('duration_seconds', 0)))
                missing = max(0, int(report.get('missing_audio_frames', 0))) / 48000
            except (TypeError, ValueError):
                duration = missing = 0
                report_error = True
            quality = ('Report unreadable' if report_error else 'Quality unknown · no report' if not report
                else str(report['error']) if report.get('error') else 'Empty recording' if not duration
                else f'Audio gaps: {missing:.2f}s ({100 * missing / duration:.1f}%)' if missing
                else 'No gaps reported')
            if not path.is_file():
                quality = 'File unavailable'
            item = QTreeWidgetItem([title, str(report.get('started', '—')).replace('T', ' ')[:19],
                f'{duration:.2f}s' if report else '—', path.suffix[1:].upper(), quality])
            item.setData(0, Qt.UserRole, value)
            item.setToolTip(0, value)
            item.setToolTip(4, quality)
            self.table.addTopLevelItem(item)
            if value == current:
                self.table.setCurrentItem(item)
        self.selection_changed()

    def selected_path(self):
        item = self.table.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def selection_changed(self, *_):
        path = self.selected_path()
        self.play_button.setEnabled(bool(path and Path(path).is_file()))
        self.folder_button.setEnabled(bool(path and Path(path).parent.is_dir()))

    def play_selected(self):
        if not getattr(self, 'permission_check', lambda _: True)('audio'):
            return
        path = self.selected_path()
        if not path or not Path(path).is_file():
            self.status.setText('Recording file is unavailable. Use Refresh or Add Files.')
            return
        self.playback_requested.emit()
        self.media.stop()
        self.media.setSource(QUrl.fromLocalFile(path))
        self.media.play()
        self.status.setText(f'Opening recording: {Path(path).name}')

    def media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.status.setText('Recording playback finished.')
        elif status == QMediaPlayer.BufferedMedia:
            self.status.setText(f'Playing recording: {Path(self.media.source().toLocalFile()).name}')

    def playback_state(self, state):
        if state == QMediaPlayer.StoppedState and self.media.error() == QMediaPlayer.NoError:
            self.status.setText('Recording playback stopped.')

    def open_folder(self):
        path = self.selected_path()
        if path and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent))):
            self.status.setText('Could not open the recording folder.')
