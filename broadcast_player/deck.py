"""Local audio deck. Fresh Qt player per item isolates late decoder callbacks."""
import math
import time

import numpy as np
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtMultimedia import (
    QAudioOutput, QAudioBufferOutput, QAudioFormat, QMediaDevices, QMediaPlayer)

from .media import availability


class LocalDeck(QObject):
    changed = Signal()
    ended = Signal()
    failed = Signal(str)
    levels = Signal(float, float)
    position = Signal(int, int)
    decoded = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.output = None
        self.tap = None
        self.device_id = None
        self.item = None
        self.state = 'stopped'
        self.volume = .7
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self.check_device)
        self.last_progress = 0.0
        self.last_position = -1
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(500)
        self.watchdog.timeout.connect(self.check_progress)

    @property
    def active(self):
        return self.state in ('loading', 'playing', 'paused')

    def start(self, item, device_id):
        self.stop()
        error = availability(item)
        if error:
            self.fail(error)
            return False
        device = next((d for d in QMediaDevices.audioOutputs()
                       if bytes(d.id()) == device_id), None)
        if device is None:
            self.fail('output_missing')
            return False
        self.device_id = bytes(device.id())
        self.item = dict(item)
        player = QMediaPlayer(self)
        self.player = player
        self.output = QAudioOutput(device, player)
        self.output.setVolume(self.volume)
        player.setAudioOutput(self.output)
        self.tap = QAudioBufferOutput(player)
        player.setAudioBufferOutput(self.tap)
        self.tap.audioBufferReceived.connect(lambda buffer: self.receive(player, buffer))
        player.mediaStatusChanged.connect(lambda status: self.media_status(player, status))
        player.playbackStateChanged.connect(lambda state: self.playback_state(player, state))
        player.errorOccurred.connect(lambda error, detail: self.fail('playback_error: ' + detail)
                                     if player is self.player else None)
        player.positionChanged.connect(lambda value: self.tick(player, value))
        self.state = 'loading'
        self.last_progress = time.monotonic()
        self.last_position = -1
        self.changed.emit()
        self.watchdog.start()
        player.setSource(QUrl.fromLocalFile(item['path']))
        player.play()
        return True

    def receive(self, player, buffer):
        if player is not self.player or not buffer.isValid():
            return
        fmt = buffer.format()
        formats = {QAudioFormat.Int16: ('<i2', 32768), QAudioFormat.Int32: ('<i4', 2147483648),
                   QAudioFormat.Float: ('<f4', 1), QAudioFormat.UInt8: ('u1', 128)}
        if fmt.sampleFormat() not in formats or fmt.channelCount() < 1:
            return
        dtype, scale = formats[fmt.sampleFormat()]
        data = np.frombuffer(buffer.constData(), dtype=dtype).astype(np.float32)
        if fmt.sampleFormat() == QAudioFormat.UInt8:
            data -= 128
        samples = data.reshape(-1, fmt.channelCount()) / scale
        self.decoded.emit(samples.copy())
        peaks = np.max(np.abs(samples), axis=0)
        db = [max(-60., 20 * math.log10(max(float(v), 1e-9))) for v in peaks]
        self.levels.emit(db[0], db[min(1, len(db) - 1)])

    def media_status(self, player, status):
        if player is not self.player:
            return
        if status == QMediaPlayer.EndOfMedia:
            self.stop()
            self.ended.emit()
        elif status == QMediaPlayer.InvalidMedia:
            self.fail('decode_failed')

    def playback_state(self, player, state):
        if player is not self.player:
            return
        if state == QMediaPlayer.PlayingState:
            self.state = 'playing'
        elif state == QMediaPlayer.PausedState:
            self.state = 'paused'
            self.levels.emit(-60., -60.)
        self.changed.emit()

    def tick(self, player, value):
        if player is not self.player:
            return
        if value != self.last_position:
            self.last_progress = time.monotonic()
            self.last_position = value
        self.position.emit(value, player.duration())

    def toggle_pause(self):
        if self.player:
            self.last_progress = time.monotonic()
            if self.state == 'paused':
                self.player.play()
            elif self.state == 'playing':
                self.player.pause()

    def seek(self, milliseconds):
        if self.player and self.player.isSeekable():
            self.last_progress = time.monotonic()
            self.player.setPosition(max(0, min(milliseconds, self.player.duration())))

    def set_volume(self, percent):
        self.volume = max(0., min(1., percent / 100))
        if self.output:
            self.output.setVolume(self.volume)

    def check_device(self):
        if self.active and not any(bytes(d.id()) == self.device_id for d in QMediaDevices.audioOutputs()):
            self.fail('output_missing')

    def check_progress(self):
        self.check_device()
        if self.state in ('loading', 'playing') and time.monotonic() - self.last_progress > 10:
            self.fail('stalled')

    def fail(self, error):
        self.stop()
        self.state = 'error'
        self.changed.emit()
        self.failed.emit(error)

    def stop(self):
        self.watchdog.stop()
        player, self.player = self.player, None
        self.output = self.tap = None
        self.state = 'stopped'
        if player:
            player.stop()
            # stop() retains the source and its Windows file handle. Clear it
            # explicitly so an operator can move/replace media after Stop.
            player.setSource(QUrl())
            player.setAudioOutput(None)
            player.setAudioBufferOutput(None)
            player.deleteLater()
        self.levels.emit(-60., -60.)
        self.changed.emit()
