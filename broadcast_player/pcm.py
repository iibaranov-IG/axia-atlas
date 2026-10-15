"""Bounded, file-backed PCM preparation and a sample-counted two-source mixer.

No Qt, output device, wall clock or database access belongs in this module.
Temporary PCM is disposable; the source media is opened read-only.
"""
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

import av
import numpy as np

from .media import availability


class PlayoutError(Exception):
    pass


@dataclass
class PreparedAudio:
    file: object
    frames: int
    rate: int
    item: dict

    def read(self, start, count):
        self.file.seek(start * 8)
        data = self.file.read(count * 8)
        if len(data) != count * 8:
            raise PlayoutError('cache_read')
        return np.frombuffer(data, dtype='<f4').reshape(-1, 2)

    def close(self):
        self.file.close()


def prepare_audio(item, rate, directory, cancelled):
    """Decode to stereo float at the selected output rate, with bounded RAM.

    Mono is duplicated at unity gain, not attenuated by a surround downmixer.
    Resampling keeps the file's entire decoded audio, including authored silence.
    """
    error = availability(item)
    if error:
        raise PlayoutError(error)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    estimated = (item['duration_ms'] * rate // 1000 + rate) * 8
    if shutil.disk_usage(directory).free < estimated + 256 * 1024**2:
        raise PlayoutError('cache_space')
    output = tempfile.TemporaryFile(prefix='atlas-pcm-', dir=directory)
    frames = 0
    try:
        with av.open(item['path'], options={'protocol_whitelist': 'file'}) as container:
            stream = container.streams.audio[0]
            layout = 'mono' if item['channels'] == 1 else 'stereo'
            resampler = av.AudioResampler(format='fltp', layout=layout, rate=rate)

            def write(converted):
                nonlocal frames
                for frame in converted:
                    if cancelled.is_set():
                        raise PlayoutError('cancelled')
                    samples = frame.to_ndarray().T
                    if samples.shape[1] == 1:
                        samples = np.repeat(samples, 2, axis=1)
                    if not np.isfinite(samples).all():
                        raise PlayoutError('decode_failed')
                    output.write(np.ascontiguousarray(samples, dtype='<f4').tobytes())
                    frames += len(samples)

            for frame in container.decode(stream):
                if cancelled.is_set():
                    raise PlayoutError('cancelled')
                write(resampler.resample(frame))
            write(resampler.resample(None))
        if not frames:
            raise PlayoutError('empty_audio')
        error = availability(item)
        if error:
            raise PlayoutError(error)
        output.flush()
        return PreparedAudio(output, frames, rate, dict(item))
    except BaseException:
        output.close()
        raise


class PcmSequence:
    """Read a sequence without adding samples between entries.

    Events are (output_frame, kind, queue_index, value). A started event for the
    next item is at the first overlap sample, completion at the old item's end.
    A linear constant-sum fade cannot add gain to two in-range correlated inputs.
    Overlap is limited to half of either file so three files never overlap.
    """
    def __init__(self, provider, count, index, rate, overlap_ms=0, offset=0,
                 stop_at=None, announce=True):
        self.provider, self.count = provider, count
        self.index, self.rate = index, rate
        self.cursor, self.frame = offset, 0
        self.overlap = round(max(0, min(10000, overlap_ms)) * rate / 1000)
        self.stop_at = stop_at
        self.events = [(0, 'started', index, offset)] if announce else []
        self.finished = False
        self.fading = False
        self.plan = None
        self.fade = 0
        self.error = None
        self.current = self.provider(index)
        self.next = None
        self.threshold = self.current.frames - min(self.overlap, (self.current.frames - offset) // 2)

    def _plan(self):
        self.plan = 0
        if self.index + 1 >= self.count or self.stop_at == self.index:
            return
        try:
            self.next = self.provider(self.index + 1)
            error = availability(self.next.item)
            if error:
                raise PlayoutError(error)
            self.plan = min(self.overlap, self.current.frames - max(self.threshold, self.cursor),
                            self.next.frames // 2)
        except PlayoutError as exc:
            # Finish the current item dry, then report the failure. Never silently
            # skip the bad item or restart its decoder in the audio callback.
            self.error = str(exc)

    def read(self, count):
        parts = []
        while not self.finished and (count > 0 or self.cursor == self.current.frames):
            if self.plan is None and self.cursor >= self.threshold:
                self._plan()
            end = self.current.frames
            if self.stop_at == self.index and not self.fading:
                self.plan, self.next, self.error = 0, None, None
            if self.plan is None:
                boundary = self.threshold
            else:
                boundary = end - self.plan
            if self.cursor < boundary:
                length = min(count, boundary - self.cursor)
                parts.append(self.current.read(self.cursor, length))
                self.cursor += length
                self.frame += length
                count -= length
                continue
            if self.plan and self.cursor < end:
                if not self.fading:
                    self.fading = True
                    self.events.extend([(self.frame, 'started', self.index + 1, 0),
                                        (self.frame, 'transition', self.index + 1, self.plan)])
                length = min(count, end - self.cursor)
                coefficient = (np.arange(self.fade, self.fade + length, dtype=np.float64) /
                               max(1, self.plan - 1))[:, None]
                mixed = (self.current.read(self.cursor, length) * (1 - coefficient) +
                         self.next.read(self.fade, length) * coefficient)
                parts.append(mixed.astype('<f4'))
                self.cursor += length
                self.fade += length
                self.frame += length
                count -= length
            if self.cursor == end:
                self.events.append((self.frame, 'completed', self.index, 0))
                if self.error or self.stop_at == self.index or self.index + 1 >= self.count:
                    self.finished = True
                    break
                if self.next is None:
                    self._plan()
                    if self.error:
                        self.finished = True
                        break
                if not self.fading:
                    self.events.append((self.frame, 'started', self.index + 1, 0))
                self.index += 1
                self.current, self.next = self.next, None
                self.cursor = self.fade
                self.plan, self.fade, self.fading = None, 0, False
                self.threshold = self.current.frames - min(self.overlap, self.current.frames // 2)
        return np.concatenate(parts) if parts else np.empty((0, 2), dtype='<f4')
