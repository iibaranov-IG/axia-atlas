"""One local output clock for the queue; cue remains an independent LocalDeck."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
from threading import Event
import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from .media import availability
from .pcm import PcmSequence, PlayoutError, prepare_audio


def discard_result(future):
    """May run in the decoder thread; never touches Qt or the catalogue."""
    try:
        future.result().close()
    except Exception:
        pass


class QueueDeck(QObject):
    changed = Signal()
    ended = Signal()
    failed = Signal(str)
    levels = Signal(float, float)
    position = Signal(int, int)
    decoded = Signal(object)  # PCM accepted by the output, before its volume.
    started = Signal(int)
    completed = Signal(int)
    transition = Signal(int, int)  # incoming index, actual overlap milliseconds
    interrupted = Signal(int)  # outgoing tail cut short by Stop/Next/seek/error

    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='atlas-preload')
        self.jobs, self.prepared, self.errors = {}, {}, {}
        self.items = []
        self.index = -1
        self.item = None
        self.device_id = None
        self.device = None
        self.state = 'stopped'
        self.volume = .7
        self.sink = self.writer = self.sequence = None
        self.sample_rate = 48000
        self.output_format = None
        self.overlap_ms = 0
        self.stop_after = False
        self.pending = b''
        self.pending_samples = None
        self.pending_offset = self.written = 0
        self.events = deque()
        self.origin = self.offset = self.current_frame = 0
        self.last_progress = 0
        self.last_processed = 0
        self.last_pump = 0
        self.resume_paused = False
        self.announce = True
        self.audible = set()
        self.transition_until = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.pump)
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self.check_device)

    @property
    def active(self):
        return self.state in ('loading', 'playing', 'paused')

    @property
    def can_change_stop(self):
        return not self.sequence or (self.last_processed >= self.transition_until and
                                     not self.sequence.fading and not self.sequence.finished and
                                     self.sequence.index == self.index)

    @property
    def next_state(self):
        index = self.index + 1
        if not self.active or index >= len(self.items) or self.stop_after:
            return ''
        if index in self.errors:
            return 'error'
        return 'ready' if index in self.prepared else 'preparing'

    def start_queue(self, items, index, device_id, overlap_ms=0, stop_after=False):
        self.stop()
        self.items = [dict(item) for item in items]
        self.index = index
        self.item = self.items[index]
        self.device_id = device_id
        self.device = next((d for d in QMediaDevices.audioOutputs() if bytes(d.id()) == device_id), None)
        if self.device is None:
            self.fail('output_missing')
            return False
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Float)
        if not self.device.isFormatSupported(fmt):
            fmt = self.device.preferredFormat()
        if fmt.channelCount() != 2 or fmt.sampleRate() <= 0 or fmt.sampleFormat() not in (
                QAudioFormat.Float, QAudioFormat.Int16, QAudioFormat.Int32):
            self.fail('output_format')
            return False
        self.output_format, self.sample_rate = fmt, fmt.sampleRate()
        self.overlap_ms, self.stop_after = overlap_ms, stop_after
        self.offset = self.current_frame = 0
        self.announce = True
        self.state = 'loading'
        self.request_preparation()
        self.timer.start()
        self.changed.emit()
        return True

    def request_preparation(self):
        start = self.sequence.index if self.sequence else self.index
        for index in range(start, min(len(self.items), start + 3)):
            if index not in self.prepared and index not in self.jobs and index not in self.errors:
                cancelled = Event()
                future = self.executor.submit(prepare_audio, self.items[index], self.sample_rate,
                                              self.cache_dir, cancelled)
                self.jobs[index] = (future, cancelled)

    def collect(self):
        changed = False
        for index, (future, _) in list(self.jobs.items()):
            if not future.done():
                continue
            del self.jobs[index]
            try:
                self.prepared[index] = future.result()
            except PlayoutError as exc:
                self.errors[index] = str(exc)
            except OSError:
                self.errors[index] = 'cache_space'
            except Exception:
                self.errors[index] = 'decode_failed'
            changed = True
        if changed:
            self.changed.emit()

    def track(self, index):
        if index in self.errors:
            raise PlayoutError(self.errors[index])
        if index not in self.prepared:
            raise PlayoutError('not_prepared')
        return self.prepared[index]

    def open_output(self):
        error = availability(self.item)
        if error:
            raise PlayoutError(error)
        self.sequence = PcmSequence(self.track, len(self.items), self.index, self.sample_rate,
                                    self.overlap_ms, self.offset,
                                    self.index if self.stop_after else None, self.announce)
        self.events.clear()
        self.origin = 0
        self.current_frame = self.offset
        self.written = self.last_processed = 0
        self.last_progress = time.monotonic()
        self.last_pump = self.last_progress
        self.sink = QAudioSink(self.device, self.output_format, self)
        self.sink.setBufferSize(self.output_format.bytesForDuration(250000))
        self.sink.setVolume(self.volume)
        self.writer = self.sink.start()
        if self.writer is None or self.sink.error() != QAudio.NoError:
            raise PlayoutError('output_open')
        if self.resume_paused:
            self.sink.suspend()
            self.state = 'paused'
        self.resume_paused = False
        self.changed.emit()

    def pump(self):
        if not self.active:
            return
        try:
            self.collect()
            if not self.sink:
                required = [self.index]
                if not self.stop_after and self.index + 1 < len(self.items):
                    required.append(self.index + 1)
                for index in required:
                    if index in self.errors:
                        raise PlayoutError(self.errors[index])
                if not all(index in self.prepared for index in required):
                    return
                self.open_output()
            if self.state == 'paused':
                return
            if self.sink.error() not in (QAudio.NoError, QAudio.UnderrunError):
                raise PlayoutError('output_open')
            frame_bytes = self.output_format.bytesPerFrame()
            now = time.monotonic()
            # Some Windows backends do not expose an Idle/Underrun transition
            # while the GUI event loop is blocked. Detect a missed feed deadline
            # independently. This is loss of continuity assurance, not a claim
            # that we measured the DAC's missing samples.
            buffered_seconds = max(0, self.written // frame_bytes - self.last_processed) / self.sample_rate
            if (self.written and not self.sequence.finished and
                    now - self.last_pump > buffered_seconds + .05):
                raise PlayoutError('output_late')
            self.last_pump = now
            processed = min(self.written // frame_bytes,
                            (self.sink.processedUSecs() * self.sample_rate + 999999) // 1000000)
            if processed > self.last_processed:
                self.last_processed = processed
                self.last_progress = time.monotonic()
            self.dispatch(processed)
            if not self.active:
                return
            if self.sequence.finished and not self.pending and processed >= self.sequence.frame:
                error = self.sequence.error
                if error:
                    self.fail(error)
                else:
                    self.stop()
                    self.ended.emit()
                return
            if self.written and self.sink.state() == QAudio.IdleState and not self.sequence.finished:
                raise PlayoutError('output_underrun')
            if time.monotonic() - self.last_progress > 10:
                raise PlayoutError('stalled')
            capacity = max(0, self.sink.bytesFree()) // frame_bytes
            if capacity:
                if not self.pending and not self.sequence.finished:
                    samples = self.sequence.read(min(capacity, 4096))
                    self.events.extend(self.sequence.events)
                    self.sequence.events.clear()
                    samples = np.clip(samples, -1., 1.)
                    fmt = self.output_format.sampleFormat()
                    if fmt == QAudioFormat.Int16:
                        encoded = np.round(samples * 32767).astype('<i2')
                        samples = encoded.astype(np.float32) / 32768
                    elif fmt == QAudioFormat.Int32:
                        encoded = np.round(samples.astype(np.float64) * 2147483647).astype('<i4')
                        samples = encoded.astype(np.float32) / 2147483648
                    else:
                        encoded = samples.astype('<f4')
                    self.pending = encoded.tobytes()
                    self.pending_samples = samples
                    self.pending_offset = 0
                    self.request_preparation()
                if self.pending:
                    written = self.writer.write(self.pending[:capacity * frame_bytes])
                    if written < 0 or written % frame_bytes:
                        raise PlayoutError('output_write')
                    if written:
                        count = written // frame_bytes
                        samples = self.pending_samples[self.pending_offset:self.pending_offset + count]
                        self.decoded.emit(samples.copy())
                        peaks = np.max(np.abs(samples), axis=0)
                        self.levels.emit(*[max(-60., 20 * math.log10(max(float(v), 1e-9))) for v in peaks])
                        self.pending_offset += count
                        self.pending = self.pending[written:]
                        self.written += written
        except PlayoutError as exc:
            self.fail(str(exc))
        except (OSError, ValueError):
            self.fail('cache_read')

    def dispatch(self, processed):
        if processed <= 0:
            return
        if self.state == 'loading':
            self.state = 'playing'
            self.changed.emit()
        while self.events and self.events[0][0] <= processed:
            if self.events[0][1] in ('started', 'transition') and self.events[0][0] == processed:
                break  # The incoming item's first sample has not left the buffer yet.
            frame, kind, index, value = self.events.popleft()
            if kind == 'started':
                self.index, self.item = index, self.items[index]
                self.origin, self.offset = frame, value
                self.audible.add(index)
                self.started.emit(index)
            elif kind == 'completed':
                self.audible.discard(index)
                self.completed.emit(index)
            elif kind == 'transition':
                self.transition_until = frame + value
                self.transition.emit(index, round(value * 1000 / self.sample_rate))
        self.current_frame = self.offset + max(0, processed - self.origin)
        track = self.prepared.get(self.index)
        duration = round(track.frames * 1000 / self.sample_rate) if track else self.item['duration_ms']
        self.position.emit(min(duration, round(self.current_frame * 1000 / self.sample_rate)), duration)
        # Keep the preceding file until its tail has left the device buffer.
        for index in list(self.prepared):
            if index < self.index - 1:
                self.prepared.pop(index).close()
        self.changed.emit()

    def set_stop_after(self, checked):
        if not self.can_change_stop:
            return
        self.stop_after = bool(checked)
        if self.sequence:
            self.sequence.stop_at = self.index if checked else None
            # A cancelled stop must allow the boundary to be planned again.
            if not checked and self.sequence.next is None and not self.sequence.error:
                self.sequence.plan = None

    def toggle_pause(self):
        if self.sink:
            if self.state == 'paused':
                self.sink.resume()
                self.last_progress = time.monotonic()
                self.last_pump = self.last_progress
                self.state = 'playing'
            elif self.state == 'playing':
                self.sink.suspend()
                self.state = 'paused'
                self.levels.emit(-60., -60.)
            self.changed.emit()

    def seek(self, milliseconds):
        if self.state not in ('playing', 'paused') or not self.can_change_stop:
            return
        track = self.track(self.index)
        paused = self.state == 'paused'
        self.release_output()
        self.offset = max(0, min(round(milliseconds * self.sample_rate / 1000), track.frames - 1))
        self.current_frame = self.offset
        self.announce = False
        self.resume_paused = paused
        self.state = 'loading'
        self.changed.emit()

    def set_volume(self, percent):
        self.volume = max(0., min(1., percent / 100))
        if self.sink:
            self.sink.setVolume(self.volume)

    def check_device(self):
        if self.active and not any(bytes(d.id()) == self.device_id for d in QMediaDevices.audioOutputs()):
            self.fail('output_missing')

    def release_output(self):
        sink, self.sink = self.sink, None
        self.writer = self.sequence = None
        if sink:
            sink.reset()  # Discard buffered sound immediately on Stop/seek.
            sink.deleteLater()
        self.pending = b''
        self.pending_samples = None
        self.events.clear()
        self.transition_until = 0

    def stop(self):
        self.timer.stop()
        for index in sorted(self.audible):
            if index != self.index:
                self.interrupted.emit(index)
        self.audible.clear()
        self.release_output()
        for future, cancelled in self.jobs.values():
            cancelled.set()
            future.add_done_callback(discard_result)
        self.jobs.clear()
        for track in self.prepared.values():
            track.close()
        self.prepared.clear()
        self.errors.clear()
        self.resume_paused = False
        self.state = 'stopped'
        self.levels.emit(-60., -60.)
        self.changed.emit()

    def fail(self, error):
        self.stop()
        self.state = 'error'
        self.changed.emit()
        self.failed.emit(error)

    def shutdown(self):
        self.stop()
        self.executor.shutdown(wait=True, cancel_futures=True)
