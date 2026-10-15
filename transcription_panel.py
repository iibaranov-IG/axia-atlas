"""File-to-text workflow. Cancellation terminates only its own worker process."""
from localization import tr
import json
import sys
from pathlib import Path
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QComboBox, QPlainTextEdit, QFileDialog, QProgressBar, QMessageBox)
from transcription import as_srt


class TranscriptionPanel(QWidget):
    def __init__(self, atlas):
        super().__init__()
        self.atlas = atlas
        self.model_dir = atlas.data_dir / 'state' / 'speech-model'
        self.process = None
        self.segments = []
        self.complete = False
        self.cancelled = False
        self.failed = False
        self.buffer = b''
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Audio to Text · local recognition · original recording is preserved')))
        self.prepare = QPushButton(tr('Prepare Offline Recognition (first use, approximately 500 MB)'))
        self.prepare.clicked.connect(lambda: self.start('prepare'))
        layout.addWidget(self.prepare)
        row = QHBoxLayout()
        self.file = QLineEdit()
        self.file.setReadOnly(True)
        self.choose = QPushButton(tr('Choose Audio File…'))
        self.choose.clicked.connect(self.choose_file)
        row.addWidget(self.file, 1); row.addWidget(self.choose)
        layout.addLayout(row)
        self.language = QComboBox()
        for label, code in [('Detect speech language', 'auto'), ('Russian', 'ru'), ('English', 'en'),
                            ('German', 'de'), ('French', 'fr'), ('Spanish', 'es'), ('Portuguese', 'pt'),
                            ('Chinese', 'zh'), ('Japanese', 'ja'), ('Arabic', 'ar'), ('Hindi', 'hi')]:
            self.language.addItem(tr(label), code)
        layout.addWidget(self.language)
        row = QHBoxLayout()
        self.run_button = QPushButton(tr('Transcribe'))
        self.run_button.clicked.connect(lambda: self.start('transcribe'))
        self.cancel = QPushButton(tr('Cancel'))
        self.cancel.clicked.connect(self.cancel_work)
        self.save_button = QPushButton(tr('Save Text…'))
        self.save_button.clicked.connect(self.save)
        for button in (self.run_button, self.cancel, self.save_button): row.addWidget(button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel(tr('Choose a recording. Recognition may contain errors; review the text before publication.'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.update_controls()

    def update_controls(self):
        busy = self.process is not None
        ready = all((self.model_dir / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json'))
        self.prepare.setVisible(not ready)
        self.prepare.setEnabled(not busy)
        self.choose.setEnabled(not busy)
        self.language.setEnabled(not busy)
        self.run_button.setEnabled(not busy and bool(self.file.text()))
        self.cancel.setEnabled(busy)
        self.save_button.setEnabled(not busy and self.complete and bool(self.segments))

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Choose Audio File'), '',
            'Audio (*.wav *.mp3 *.flac *.m4a *.ogg *.aac *.wma)')
        if path:
            self.file.setText(path)
            self.text.clear(); self.segments = []; self.complete = False
            self.update_controls()
            ready = all((self.model_dir / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json'))
            self.status.setText(tr('Recording selected. Press Transcribe.') if ready else tr('Recording selected. Press Transcribe to prepare recognition and continue.'))

    def start(self, mode):
        if self.process or not self.atlas.access.allowed('audio'): return
        if mode == 'prepare' and not self.atlas.access.allowed('downloads'):
            self.status.setText(tr('Downloads are not permitted for this account.')); return
        if mode == 'transcribe':
            if not Path(self.file.text()).is_file():
                self.status.setText(tr('Audio file is unavailable. Choose the recording again.')); return
            ready = all((self.model_dir / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json'))
            if not ready:
                if not self.atlas.access.allowed('downloads'):
                    self.status.setText(tr('Recognition needs first-time preparation. Ask an administrator to download the recognition files.')); return
                answer = QMessageBox.question(self, tr('Prepare recognition'),
                    tr('First use requires approximately 500 MB of recognition files. Download them and then transcribe this recording? Audio stays on this computer.'))
                if answer != QMessageBox.Yes: return
                mode = 'prepare_transcribe'
        self.signature = self.atlas.permission_signature
        self.segments = []; self.complete = False; self.cancelled = False; self.buffer = b''
        self.failed = False
        self.text.clear()
        self.progress.setRange(0, 0)
        self.status.setText((tr('Downloading recognition files…') if mode in ('prepare', 'prepare_transcribe') else tr('Recognizing speech locally…')))
        process = self.process = QProcess(self)
        args = ['--transcribe-worker', mode, str(self.model_dir), self.file.text(), self.language.currentData()]
        if not getattr(sys, 'frozen', False): args.insert(0, str(Path(__file__).with_name('main.py')))
        process.readyReadStandardOutput.connect(self.read_output)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.process_error)
        self.update_controls()
        process.start(sys.executable, args)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.status.setText(tr('Recognition could not start.'))
            self.finished(-1, QProcess.CrashExit)

    def read_output(self):
        if self.process is None: return
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try: data = json.loads(line)
            except (ValueError, UnicodeError): continue
            if self.signature != self.atlas.permission_signature or not self.atlas.access.allowed('audio'):
                self.cancel_work(); self.text.clear(); self.segments = []; return
            kind = data.get('kind')
            if kind == 'segment':
                self.segments.append(data)
                self.text.appendPlainText(data['text'])
                self.progress.setRange(0, 100); self.progress.setValue(data['progress'])
            elif kind == 'done':
                self.complete = True
                self.status.setText((tr('Transcription complete. Review the text before publication.') if data['count'] else tr('No speech was recognized in this recording.')))
            elif kind == 'recognizing':
                self.status.setText(tr('Recognizing speech locally…'))
            elif kind == 'ready':
                self.complete = True
                self.status.setText(tr('Offline recognition is ready. Choose an audio file.'))
            elif kind == 'error':
                self.failed = True
                self.status.setText((tr('Recognition failed: ') + data['message']))

    def finished(self, code, status):
        if self.process is None: return
        self.read_output()
        process, self.process = self.process, None
        process.deleteLater()
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if self.complete else 0)
        if self.cancelled:
            self.complete = False
            self.status.setText(tr('Cancelled. No completed transcript was saved.'))
        elif code and not self.failed:
            self.complete = False
            self.status.setText(tr('Recognition stopped unexpectedly. Try again with a supported audio file.'))
        self.update_controls()

    def cancel_work(self):
        self.cancelled = True
        if self.process: self.process.kill()

    def dispose(self):
        self.cancel_work()
        if self.process: self.process.waitForFinished(3000)

    def save(self):
        if not self.atlas.access.allowed('audio') or not self.complete or not self.segments: return
        path, selected = QFileDialog.getSaveFileName(self, tr('Save Transcription'),
            str(Path(self.file.text()).with_suffix('.txt')), 'Text (*.txt);;Subtitles (*.srt)')
        if not path: return
        destination = Path(path)
        if destination.suffix.lower() not in ('.txt', '.srt'):
            destination = Path(path + ('.srt' if '*.srt' in selected else '.txt'))
        try:
            # Preserve originals and existing documents even if dialog confirms overwrite.
            with destination.open('x', encoding='utf-8-sig') as output:
                output.write(as_srt(self.segments) if destination.suffix.lower() == '.srt' else self.text.toPlainText() + '\n')
            self.status.setText((tr('Transcript saved: ') + str(destination)))
        except OSError as exc:
            QMessageBox.warning(self, tr('Transcript not saved'), str(exc))
