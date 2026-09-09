"""Stereo Livewire L24/48000 RTP monitoring with explicit source identity.

Format reference: https://docs.telosalliance.com/docs/playing-livewire-streams-with-standard-media-players
"""
import math
import struct
import threading
import time
import numpy as np
import soxr
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from recording import WaveRecorder, MP3Recorder, MP3_BITRATES, WAV_FORMATS, estimated_mb_per_hour, pcm24_to_pcm16
from array import array
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtNetwork import QUdpSocket, QHostAddress, QNetworkInterface, QAbstractSocket
from PySide6.QtMultimedia import QMediaDevices, QAudioFormat, QAudioSink, QAudio
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QLineEdit, QCheckBox, QPushButton, QComboBox, QSlider, QProgressBar, QFileDialog)


def decode_rtp(packet, sample_width=2):
    if len(packet) < 12 or packet[0] >> 6 != 2 or packet[1] & 127 != 96:
        raise ValueError('Requires stereo Livewire L24/48000, RTP payload type 96')
    offset = 12 + (packet[0] & 15) * 4
    if len(packet) < offset:
        raise ValueError('Truncated RTP contributors')
    if packet[0] & 16:
        if len(packet) < offset + 4:
            raise ValueError('Truncated RTP extension')
        offset += 4 + int.from_bytes(packet[offset + 2:offset + 4], 'big') * 4
    end = len(packet)
    if packet[0] & 32:
        padding = packet[-1]
        if padding == 0 or padding > end - offset:
            raise ValueError('Invalid RTP padding')
        end -= padding
    payload = packet[offset:end]
    if not payload or len(payload) % 6:
        raise ValueError('Payload is not packed 24-bit stereo')
    if sample_width == 3:
        pcm = bytearray(len(payload))
        pcm[0::3], pcm[1::3], pcm[2::3] = payload[2::3], payload[1::3], payload[0::3]
    elif sample_width == 2:
        pcm = bytearray(len(payload) // 3 * 2)
        pcm[0::2], pcm[1::2] = payload[1::3], payload[0::3]
    else:
        raise ValueError('Unsupported sample width')
    seq, timestamp, ssrc = struct.unpack('!HII', packet[2:12])
    return seq, timestamp, ssrc, bytes(pcm)


class OutputConverter:
    """Stateful conversion; recreated when changing source or after a dropout."""
    def __init__(self, rate, sample_format):
        self.sample_format = sample_format
        self.resampler = soxr.ResampleStream(48000, rate, 2, dtype='float32') if rate != 48000 else None

    def convert(self, pcm, last=False):
        samples = np.frombuffer(pcm, dtype='<i2').reshape(-1, 2).astype(np.float32) / 32768
        if self.resampler:
            samples = self.resampler.resample_chunk(samples, last=last)
        if self.sample_format == QAudioFormat.Float:
            return samples.astype('<f4').tobytes()
        if self.sample_format == QAudioFormat.Int32:
            return np.clip(samples.astype(np.float64) * 2147483648, -2147483648, 2147483647).astype('<i4').tobytes()
        return np.clip(samples * 32768, -32768, 32767).astype('<i2').tobytes()


class AudioBuffer:
    def __init__(self, enforce_ssrc=True):
        self.enforce_ssrc = enforce_ssrc
        self.lock = threading.Lock()
        self.pcm = bytearray()
        self.packets = self.gaps = self.late = self.invalid = self.overflows = self.foreign = 0
        self.seq = self.ssrc = self.timestamp = None
        self.frames = 0
        self.last_packet = 0.0
        self.left = self.right = -60.0
        self.error = ''
        self.bound = False
        self.recorder = None

    def feed(self, packet):
        try:
            seq, stamp, ssrc, pcm24 = decode_rtp(packet, sample_width=3)
            pcm = pcm24_to_pcm16(pcm24)
        except ValueError:
            with self.lock:
                self.invalid += 1
            return
        with self.lock:
            if self.enforce_ssrc and self.ssrc is not None and self.ssrc != ssrc:
                self.foreign += 1
                return
            if self.seq is not None:
                delta = (seq - self.seq) & 65535
                if delta == 0 or delta > 32768:
                    self.late += 1
                    return
                if delta > 1:
                    self.gaps += delta - 1
                    missing = (stamp - self.timestamp - self.frames) & 0xffffffff
                    if missing <= 9600:
                        self.pcm.extend(bytes(missing * 4))
                    else:
                        self.pcm.clear()
            self.seq, self.timestamp, self.ssrc = seq, stamp, ssrc
            self.frames = len(pcm) // 4
            self.pcm.extend(pcm)
            if len(self.pcm) > 57600:  # no more than 300 ms of queued audio
                del self.pcm[:-19200]
                self.overflows += 1
            self.packets += 1
            self.last_packet = time.monotonic()
            if self.recorder:
                self.recorder.feed(pcm24 if self.recorder.input_width == 3 else pcm, stamp)
            samples = array('h', pcm)  # application target is little-endian Windows
            left = max((abs(s) for s in samples[0::2]), default=0)
            right = max((abs(s) for s in samples[1::2]), default=0)
            self.left = max(-60, 20 * math.log10(max(left, 1) / 32768))
            self.right = max(-60, 20 * math.log10(max(right, 1) / 32768))


class AudioReceiver(QThread):
    def __init__(self, source, interface_index):
        super().__init__()
        self.source = dict(source)
        self.interface_index = interface_index
        # Legacy Livewire observed on LiveMic SYSV 1.1.1 changes bytes 8..11
        # in every 12-frame packet. Sender IP and destination group below
        # provide source identity; do not treat that field as a stable SSRC.
        self.buffer = AudioBuffer(enforce_ssrc=False)

    def run(self):
        socket = QUdpSocket()
        try:
            if not socket.bind(QHostAddress.AnyIPv4, 5004,
                    QAbstractSocket.ShareAddress | QAbstractSocket.ReuseAddressHint):
                raise OSError(socket.errorString())
            socket.setSocketOption(QAbstractSocket.ReceiveBufferSizeSocketOption, 4 * 1024 * 1024)
            interface = QNetworkInterface.interfaceFromIndex(self.interface_index)
            if not socket.joinMulticastGroup(QHostAddress(self.source['multicast']), interface):
                raise OSError(socket.errorString())
            with self.buffer.lock:
                self.buffer.bound = True
            while not self.isInterruptionRequested():
                if not socket.hasPendingDatagrams():
                    socket.waitForReadyRead(100)
                for _ in range(256):
                    if self.isInterruptionRequested() or not socket.hasPendingDatagrams():
                        break
                    datagram = socket.receiveDatagram(65535)
                    if (datagram.senderAddress().toString() != self.source['ip'] or
                            datagram.destinationAddress().toString() != self.source['multicast']):
                        with self.buffer.lock:
                            self.buffer.foreign += 1
                        continue
                    self.buffer.feed(bytes(datagram.data()))
        except OSError as exc:
            with self.buffer.lock:
                self.buffer.error = str(exc)
        finally:
            socket.close()


class AudioSourceList(QWidget):
    selected = Signal(object)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.sources = {}
        self.signatures = {}
        self.favorites = set(settings.value('audio_favorites', [], type=list))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find channel, source or device…')
        layout.addWidget(self.search)
        self.only_favorites = QCheckBox('Favorites only')
        layout.addWidget(self.only_favorites)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(['Channel / Source', 'Device'])
        self.tree.setColumnWidth(0, 230)
        layout.addWidget(self.tree)
        self.favorite_button = QPushButton('Add / Remove Favorite')
        self.favorite_button.setEnabled(False)
        layout.addWidget(self.favorite_button)
        self.search.textChanged.connect(self.filter)
        self.only_favorites.toggled.connect(self.filter)
        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.tree.currentItemChanged.connect(self.pick)

    @staticmethod
    def key(source):
        return f'{source["ip"]}|{source["multicast"]}|{source["slot"]}'

    def update_device(self, device):
        sources = device.get('inspection_sources') or device.get('sources', [])
        signature = repr((sources, device.get('name'), device.get('device_type')))
        if self.signatures.get(device['ip']) == signature:
            return
        self.signatures[device['ip']] = signature
        for key in [key for key, value in self.sources.items() if value['ip'] == device['ip']]:
            del self.sources[key]
        for source in sources:
            if (source.get('channel') and source.get('enabled') is not False
                    and source.get('multicast', '').startswith('239.')):
                value = dict(source, ip=device['ip'], device=device.get('name') or device.get('device_type', ''),
                             channels=source.get('channels', 2))
                self.sources[self.key(value)] = value
        current = self.tree.currentItem()
        current_key = current.data(0, Qt.UserRole) if current else None
        self.tree.blockSignals(True)
        self.tree.clear()
        for key, source in sorted(self.sources.items(), key=lambda pair: (pair[1].get('channel') or 0, pair[0])):
            star = '★ ' if key in self.favorites else ''
            suffix = ' [disabled]' if source.get('enabled') is False else ''
            item = QTreeWidgetItem([f'{star}{source.get("channel") or "—"} · {source["name"] or "Unnamed"}{suffix}', source['ip']])
            item.setData(0, Qt.UserRole, key)
            item.setToolTip(0, f'{source["device"]}\n{source["multicast"]}\nSelection does not start playback.')
            self.tree.addTopLevelItem(item)
            if key == current_key:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self.filter()

    def pick(self, item, *_):
        self.favorite_button.setEnabled(item is not None)
        if item:
            self.selected.emit(dict(self.sources[item.data(0, Qt.UserRole)]))

    def select_source(self, source):
        key = self.key(source)
        self.search.clear()
        self.only_favorites.setChecked(False)
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, Qt.UserRole) == key:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def toggle_favorite(self):
        item = self.tree.currentItem()
        if not item:
            return
        key = item.data(0, Qt.UserRole)
        self.favorites.symmetric_difference_update({key})
        self.settings.setValue('audio_favorites', sorted(self.favorites))
        text = item.text(0).removeprefix('★ ')
        item.setText(0, ('★ ' if key in self.favorites else '') + text)
        self.filter()

    def filter(self, *_):
        query = self.search.text().casefold()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            key = item.data(0, Qt.UserRole)
            source = self.sources[key]
            item.setHidden(not (query in f'{item.text(0)} {source["ip"]} {source["device"]}'.casefold()
                and (not self.only_favorites.isChecked() or key in self.favorites)))


class CompactPlayer(QWidget):
    logged = Signal(str)
    failed = Signal(str)
    recording_finished = Signal(str)
    monitoring_started = Signal()

    def __init__(self, interface_provider, settings=None):
        super().__init__()
        self.interface_provider = interface_provider
        self.settings = settings
        self.source = None
        self.receiver = None
        self.sink = None
        self.writer = None
        self.converter = None
        self.output_pending = bytearray()
        self.written_bytes = 0
        self.recorder = None
        self.last_recording = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.title = QLabel('No audio source selected')
        self.title.setWordWrap(True)
        self.title.setStyleSheet('font-weight:600;')
        layout.addWidget(self.title)
        self.state = QLabel('Stopped')
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.meters = []
        for name in ('L', 'R'):
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            meter = QProgressBar()
            meter.setRange(-60, 0)
            meter.setValue(-60)
            meter.setFormat('— dBFS')
            row.addWidget(meter)
            layout.addLayout(row)
            self.meters.append(meter)
        self.outputs = QComboBox()
        self.output_devices = QMediaDevices.audioOutputs()
        for device in self.output_devices:
            self.outputs.addItem(device.description())
        self.outputs.setToolTip('Audio output device')
        layout.addWidget(self.outputs)
        row = QHBoxLayout()
        self.play = QPushButton('Play')
        self.play.setEnabled(False)
        self.play.clicked.connect(self.toggle)
        row.addWidget(self.play)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(15)
        self.volume.setToolTip('Playback volume')
        self.volume.valueChanged.connect(lambda value: self.sink.setVolume(value / 100) if self.sink else None)
        row.addWidget(QLabel('Volume'))
        row.addWidget(self.volume)
        layout.addLayout(row)
        format_row = QHBoxLayout()
        self.record_format = QComboBox()
        self.record_format.addItems(['WAV', 'MP3'])
        self.record_bitrate = QComboBox()
        for bitrate in MP3_BITRATES:
            self.record_bitrate.addItem(f'{bitrate} kbps', bitrate)
        self.record_bitrate.setCurrentIndex(1)
        self.wav_quality = QComboBox()
        self.wav_quality.setMinimumContentsLength(16)
        self.wav_quality.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for sample_rate, sample_width in WAV_FORMATS:
            self.wav_quality.addItem(f'{sample_rate / 1000:g} kHz / {sample_width * 8}-bit', [sample_rate, sample_width])
        self.wav_quality.setCurrentIndex(1)
        if settings:
            self.record_format.setCurrentText(settings.value('recording_format', 'WAV'))
            saved_bitrate = settings.value('recording_mp3_bitrate', 192, type=int)
            index = self.record_bitrate.findData(saved_bitrate)
            if index >= 0:
                self.record_bitrate.setCurrentIndex(index)
            saved_rate = settings.value('recording_wav_rate', 48000, type=int)
            saved_width = settings.value('recording_wav_width', 2, type=int)
            for index in range(self.wav_quality.count()):
                if self.wav_quality.itemData(index) == [saved_rate, saved_width]:
                    self.wav_quality.setCurrentIndex(index)
        format_row.addWidget(QLabel('Record as'))
        format_row.addWidget(self.record_format)
        format_row.addWidget(self.record_bitrate)
        format_row.addWidget(self.wav_quality)
        layout.addLayout(format_row)
        self.record_size = QLabel('')
        layout.addWidget(self.record_size)
        record_row = QHBoxLayout()
        self.record_button = QPushButton('Record…')
        self.record_button.setEnabled(False)
        self.record_button.setToolTip('Record the selected channel. Stop Recording keeps monitoring active. Changing source or stopping playback finalizes the file.')
        self.record_button.clicked.connect(self.toggle_recording)
        record_row.addWidget(self.record_button)
        self.record_status = QLabel('Not recording')
        self.record_status.setWordWrap(True)
        record_row.addWidget(self.record_status, 1)
        layout.addLayout(record_row)
        self.record_path = QLabel('')
        self.record_path.setWordWrap(True)
        self.record_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.record_path)
        self.open_recording_button = QPushButton('Open Recording Folder')
        self.open_recording_button.setEnabled(False)
        self.open_recording_button.clicked.connect(self.open_recording_folder)
        layout.addWidget(self.open_recording_button)
        self.detail_label = QLabel('Select a source in the Audio tab. Stereo Livewire L24 / 48 kHz is supported.')
        self.detail_label.setWordWrap(True)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.pump)
        self.last_ui = 0
        self.record_format.currentTextChanged.connect(self.update_recording_format)
        self.record_bitrate.currentIndexChanged.connect(self.update_recording_format)
        self.wav_quality.currentIndexChanged.connect(self.update_recording_format)
        self.update_recording_format()

    def update_recording_format(self, *_):
        format_name = self.record_format.currentText()
        bitrate = self.record_bitrate.currentData()
        sample_rate, sample_width = self.wav_quality.currentData()
        self.record_bitrate.setVisible(format_name == 'MP3')
        self.wav_quality.setVisible(format_name == 'WAV')
        self.wav_quality.setEnabled(self.recorder is None and format_name == 'WAV')
        self.record_bitrate.setEnabled(self.recorder is None and format_name == 'MP3')
        self.record_format.setEnabled(self.recorder is None)
        size = estimated_mb_per_hour(format_name, bitrate, sample_rate, sample_width)
        rate_text = (f'{sample_rate * sample_width * 8 * 2 / 1000:g} kbps' if format_name == 'WAV' else
                     f'{bitrate} kbps CBR')
        self.record_size.setText(f'{rate_text} · stereo · approx. {size:.1f} MB/hour')
        self.record_size.setToolTip('Decimal MB, excluding headers and the event report. WAV 48 kHz / 24-bit preserves the received samples. WAV 44.1 kHz is resampled. MP3 uses constant bitrate.')
        if self.settings:
            self.settings.setValue('recording_format', format_name)
            self.settings.setValue('recording_mp3_bitrate', bitrate)
            self.settings.setValue('recording_wav_rate', sample_rate)
            self.settings.setValue('recording_wav_width', sample_width)

    def select(self, source):
        was_playing = self.receiver is not None
        self.stop()
        self.source = dict(source)
        self.title.setText(f'{source.get("channel") or "—"} · {source["name"] or "Unnamed source"}\n{source["ip"]}')
        self.detail_label.setText(f'Selected source: {source["ip"]} → {source["multicast"]}\n'
            f'Channel: {source.get("channel") or "Unknown"} · {source["name"] or "Unnamed source"}\n'
            'No audio statistics for this selection yet. Press Play to receive the stream.')
        allowed = source.get('enabled') is not False and source.get('channels', 2) == 2
        self.play.setEnabled(allowed and getattr(self, 'permission_check', lambda _: True)('audio'))
        self.record_button.setEnabled(allowed and getattr(self, 'permission_check', lambda _: True)('record'))
        self.state.setText('Ready · press Play' if allowed else 'Source disabled or unsupported channel count')
        if was_playing and allowed:
            self.start()

    def toggle(self):
        self.stop() if self.receiver else self.start()

    def start(self):
        if not getattr(self, 'permission_check', lambda _: True)('audio'):
            self.state.setText('Audio monitoring is not permitted for this account.')
            return
        if not self.source or self.receiver:
            return
        self.monitoring_started.emit()
        interface = self.interface_provider()
        if interface is None:
            self.state.setText('Select the broadcast network adapter in Network Discovery.')
            return
        if not self.output_devices or self.outputs.currentIndex() < 0:
            self.state.setText('No audio output is available.')
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        device = self.output_devices[self.outputs.currentIndex()]
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        if fmt.channelCount() != 2 or fmt.sampleFormat() not in (QAudioFormat.Float, QAudioFormat.Int16, QAudioFormat.Int32):
            self.state.setText('Selected output has no supported stereo format.')
            return
        self.output_format = fmt
        self.converter = OutputConverter(fmt.sampleRate(), fmt.sampleFormat())
        self.output_pending = bytearray()
        self.in_dropout = False
        self.prefilled = False
        self.output_underruns = 0
        self.sink = QAudioSink(device, fmt, self)
        self.sink.setBufferSize(fmt.bytesForDuration(250000))
        self.sink.setVolume(self.volume.value() / 100)
        self.writer = self.sink.start()
        if self.writer is None or self.sink.error() != QAudio.NoError:
            self.stop()
            self.state.setText('Could not open the selected audio output.')
            return
        self.receiver = AudioReceiver(self.source, interface.index())
        self.receiver.start()
        self.written_bytes = 0
        self.sink.stateChanged.connect(self.output_state_changed)
        self.play.setText('Stop')
        self.outputs.setEnabled(False)
        self.state.setText('Waiting for the selected stream…')
        self.detail_label.setText(f'Source: {self.source["ip"]} → {self.source["multicast"]}\nWaiting for the selected stream…')
        self.started_at = time.monotonic()
        self.last_ui = 0
        self.previous_gaps = 0
        self.previous_dropouts = 0
        self.timer.start()
        self.logged.emit(f'Audio monitor started: {self.source["ip"]} / {self.source["multicast"]}')

    def output_state_changed(self, state):
        if state == QAudio.IdleState and self.written_bytes and not self.in_dropout:
            self.output_underruns += 1

    def stop(self):
        self.timer.stop()
        self.stop_recording('Playback stopped or source changed')
        if self.receiver:
            self.detail_label.setText('Last session · stopped\n' + self.detail_label.text().removeprefix('Last session · stopped\n'))
        if self.sink:
            self.sink.reset()  # discard queued old audio before a source label changes
            self.sink.deleteLater()
            self.sink = self.writer = None
        if self.receiver:
            self.receiver.requestInterruption()
            self.receiver.wait(1500)
            self.receiver.deleteLater()
            self.receiver = None
            self.logged.emit('Audio monitor stopped.')
        if self.converter:
            self.converter.resampler = None
            self.converter = None
        self.output_pending.clear()
        self.outputs.setEnabled(True)
        self.play.setText('Play')
        self.state.setText('Stopped')
        for meter in self.meters:
            meter.setValue(-60)
            meter.setFormat('— dBFS')

    def toggle_recording(self):
        if not getattr(self, 'permission_check', lambda _: True)('record'):
            self.record_status.setText('Recording is not permitted for this account.')
            return
        if self.recorder:
            self.stop_recording()
            return
        if not self.source:
            return
        extension = self.record_format.currentText().lower()
        name = f'Atlas_{self.source["ip"]}_ch{self.source.get("channel", "unknown")}_{datetime.now():%Y%m%d_%H%M%S}.{extension}'
        description = 'MP3 audio (*.mp3)' if extension == 'mp3' else 'Wave audio (*.wav)'
        initial_path = str(Path(self.settings.value('recording_folder', '')) / name) if self.settings else name
        path, _ = QFileDialog.getSaveFileName(self, 'Record Selected Channel', initial_path, description)
        if not path:
            return
        if Path(path).suffix and Path(path).suffix.lower() != '.' + extension:
            self.record_status.setText(f'The selected format requires a .{extension} file. Choose Record again to correct the name.')
            return
        if not path.lower().endswith('.' + extension):
            path += '.' + extension
        if not self.receiver:
            self.start()
        if self.receiver:
            self.start_recording(path)

    def start_recording(self, path):
        if not getattr(self, 'permission_check', lambda _: True)('record'):
            self.record_status.setText('Recording is not permitted for this account.')
            return
        if not self.receiver or self.recorder:
            return False
        try:
            sample_rate, sample_width = self.wav_quality.currentData()
            recorder = (MP3Recorder(path, self.source, self.record_bitrate.currentData(), input_width=3)
                        if self.record_format.currentText() == 'MP3' else
                        WaveRecorder(path, self.source, sample_rate=sample_rate, sample_width=sample_width, input_width=3))
        except (OSError, ValueError, RuntimeError) as exc:
            self.record_status.setText(f'Could not create recording: {exc}')
            self.failed.emit(self.record_status.text())
            return False
        with self.receiver.buffer.lock:
            self.receiver.buffer.recorder = recorder
        self.recorder = recorder
        self.update_recording_format()
        if self.settings:
            self.settings.setValue('recording_folder', str(Path(path).resolve().parent))
        self.last_recording = Path(path)
        self.record_path.setText(Path(path).name)
        self.record_path.setToolTip(str(Path(path).resolve()))
        self.record_button.setText('Stop Recording')
        self.record_status.setText('Armed · waiting for audio')
        self.open_recording_button.setEnabled(True)
        self.logged.emit(f'Recording armed: {self.source["ip"]} / {self.source["multicast"]} → {path}')
        return True

    def stop_recording(self, reason='User stopped recording'):
        if not self.recorder:
            return
        if self.receiver:
            with self.receiver.buffer.lock:
                self.receiver.buffer.recorder = None
        recorder = self.recorder
        recorder.stop(reason)
        self.recorder = None
        self.update_recording_format()
        self.record_button.setText('Record…')
        if recorder.error:
            message = recorder.error
        elif not recorder.frames:
            message = f'No audio received · empty {recorder.format_name} file'
        else:
            missing = recorder.silence_frames / 48000
            message = (f'{recorder.format_name} saved with audio gaps · {missing:.3f}s missing '
                       f'({100 * missing / recorder.duration_seconds:.1f}%)'
                       if missing else f'{recorder.format_name} saved {recorder.duration_seconds:.1f}s')
        self.record_status.setText(message)
        if recorder.finished:
            self.recording_finished.emit(str(recorder.path))
        if recorder.error:
            self.failed.emit(f'{message}: {recorder.path}')
        else:
            self.logged.emit(f'{message}: {recorder.path}')

    def open_recording_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if self.last_recording:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_recording.resolve().parent))):
                self.record_status.setText('Could not open recording folder.')

    def pump(self):
        if not self.receiver or not self.sink:
            return
        buffer = self.receiver.buffer
        now = time.monotonic()
        # Keep the receiver lock limited to copying PCM and counters. Resampling,
        # Windows audio writes and widget updates must not block UDP reception.
        pcm = b''
        with buffer.lock:
            dropout = bool(buffer.last_packet and now - buffer.last_packet > .5)
            if dropout:
                buffer.pcm.clear()
            elif not self.output_pending:
                if not self.prefilled and len(buffer.pcm) >= 19200:  # 100 ms startup reserve
                    self.prefilled = True
                if self.prefilled:
                    count = min(len(buffer.pcm), 19200) // 4 * 4
                    pcm = bytes(buffer.pcm[:count])
                    del buffer.pcm[:count]
            buffer = SimpleNamespace(**{name: getattr(buffer, name) for name in (
                'error', 'last_packet', 'left', 'right', 'packets', 'gaps',
                'late', 'invalid', 'foreign', 'overflows')})
        if buffer.error:
            error = buffer.error
        else:
            error = ''
        dropout = bool(buffer.last_packet and now - buffer.last_packet > .5)
        if dropout and not self.in_dropout:
            self.prefilled = False
            self.output_pending.clear()
            self.converter = OutputConverter(self.output_format.sampleRate(), self.output_format.sampleFormat())
            self.sink.reset()
            self.writer = self.sink.start()
        self.in_dropout = dropout
        if pcm:
            self.output_pending.extend(self.converter.convert(pcm))
        frame_bytes = self.output_format.bytesPerFrame()
        count = min(len(self.output_pending), max(0, self.sink.bytesFree())) // frame_bytes * frame_bytes
        if count and self.writer:
            written = self.writer.write(bytes(self.output_pending[:count]))
            if written > 0:
                del self.output_pending[:written]
                self.written_bytes += written
            elif written < 0:
                error = 'Audio output write failed.'
        if now - self.last_ui > .1:
            self.last_ui = now
            receiving = buffer.last_packet and now - buffer.last_packet < .5
            levels = (buffer.left, buffer.right) if receiving else (-60, -60)
            for meter, level in zip(self.meters, levels):
                meter.setValue(round(level))
                meter.setFormat(f'{level:.1f} dBFS' if receiving else '— dBFS')
            elapsed = max(.1, now - self.started_at)
            self.state.setText('Playing selected stream' if receiving and self.written_bytes else
                'No compatible audio received' if buffer.invalid else 'Buffering selected stream…' if receiving else 'Waiting for selected stream…')
            self.detail_label.setText(f'Source: {self.source["ip"]} → {self.source["multicast"]}\n'
                f'Packets: {buffer.packets} · average {buffer.packets / elapsed:.0f}/s\n'
                f'Sequence gaps: {buffer.gaps} · late/duplicate: {buffer.late}\n'
                f'Missing packets: {100 * buffer.gaps / max(1, buffer.packets + buffer.gaps):.1f}% · gaps also affect recordings\n'
                f'Unsupported packets: {buffer.invalid} · other source: {buffer.foreign}\n'
                f'Buffer resets: {buffer.overflows} · output underruns: {self.output_underruns}\n'
                f'PCM sent to output: {self.written_bytes} bytes\n'
                f'Levels are measured before playback volume. Output: {self.output_format.sampleRate()} Hz / stereo / {self.output_format.sampleFormat().name}.')
            if self.recorder:
                elapsed_recording = self.recorder.duration_seconds
                minutes, seconds = divmod(int(elapsed_recording), 60)
                format_name = self.recorder.format_name
                quality = f' {self.recorder.bitrate}k' if self.recorder.bitrate else ''
                message = f'REC {minutes:02d}:{seconds:02d} · {format_name}{quality}' if self.recorder.frames else 'Armed · waiting for audio'
                missing = self.recorder.silence_frames / 48000
                if missing:
                    message += f' · missing {missing:.3f}s'
                self.record_status.setText(message)
                if not receiving and self.recorder.frames:
                    self.record_status.setText(message + ' · waiting for stream')
            if buffer.gaps > self.previous_gaps:
                self.previous_dropouts = now
            self.previous_gaps = buffer.gaps
            if receiving and now - self.previous_dropouts < 3:
                loss = 100 * buffer.gaps / max(1, buffer.packets + buffer.gaps)
                self.state.setText(f'Audio gaps · {loss:.1f}% packets missing')
        if self.recorder and self.recorder.error:
            self.stop_recording('Recording error')
        if self.sink.error() not in (QAudio.NoError, QAudio.UnderrunError):
            error = f'Audio output error: {self.sink.error().name}'
        if error:
            self.stop()
            self.state.setText(error)
