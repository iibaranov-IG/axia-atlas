"""Cancellable full-file decoding in a worker; no network media or shell calls."""
import os
from pathlib import Path

import av
from PySide6.QtCore import QThread, Signal

EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac'}


class ImportCancelled(Exception):
    pass


def inspect_media(filename, cancelled=lambda: False):
    path = Path(filename).expanduser().resolve()
    result = dict(path=os.path.normcase(str(path)), title=path.stem, duration_ms=0,
                  sample_rate=0, channels=0, codec='', size=0, mtime_ns=0,
                  status='invalid', error='')
    try:
        if path.suffix.lower() not in EXTENSIONS:
            raise ValueError('unsupported')
        before = path.stat()
        result.update(size=before.st_size, mtime_ns=before.st_mtime_ns)
        # Some decoders recalculate WAV duration from the surviving bytes and
        # accept a truncated RIFF as a shorter, valid file. Retain this evidence.
        with path.open('rb') as raw:
            header = raw.read(12)
        if len(header) == 12 and header[:4] == b'RIFF' and header[8:12] == b'WAVE':
            if int.from_bytes(header[4:8], 'little') + 8 > before.st_size:
                raise ValueError('truncated')
        # The protocol whitelist also rejects file formats which refer to remote media.
        with av.open(str(path), options={'protocol_whitelist': 'file'}) as container:
            if len(container.streams.audio) != 1 or container.streams.video:
                raise ValueError('audio_only')
            stream = container.streams.audio[0]
            channels = stream.codec_context.channels
            rate = stream.codec_context.sample_rate
            if channels not in (1, 2) or rate <= 0:
                raise ValueError('mono_stereo')
            samples = 0
            for frame in container.decode(stream):
                if cancelled():
                    raise ImportCancelled()
                if frame.sample_rate != rate or len(frame.layout.channels) != channels:
                    raise ValueError('format_changed')
                if frame.is_corrupt:
                    raise ValueError('decode_failed')
                samples += frame.samples
            if samples <= 0:
                raise ValueError('empty_audio')
            duration = samples / rate
            if stream.duration is not None:
                declared = float(stream.duration * stream.time_base)
                if declared - duration > max(.15, declared * .001):
                    raise ValueError('truncated')
            metadata = dict(container.metadata, **stream.metadata)
            result.update(title=metadata.get('title', path.stem)[:500],
                          duration_ms=round(duration * 1000), sample_rate=rate,
                          channels=channels, codec=stream.codec_context.name)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('changed')
        result['status'] = 'ready'
    except ImportCancelled:
        raise
    except FileNotFoundError:
        result['error'] = 'missing'
    except PermissionError:
        result['error'] = 'unreadable'
    except (ValueError, OSError, av.FFmpegError) as exc:
        known = {'unsupported', 'audio_only', 'mono_stereo', 'format_changed',
                 'empty_audio', 'truncated', 'changed', 'decode_failed'}
        result['error'] = str(exc) if str(exc) in known else 'decode_failed'
    return result


def availability(media):
    if not media:
        return 'missing'
    if media['status'] != 'ready':
        return media['error'] or 'decode_failed'
    try:
        current = Path(media['path']).stat()
        if (current.st_size, current.st_mtime_ns) != (media['size'], media['mtime_ns']):
            return 'changed'
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unreadable'
    return ''


class ImportWorker(QThread):
    inspected = Signal(object)
    progress = Signal(int, int, str)
    failed = Signal(str)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))

    def run(self):
        try:
            for index, path in enumerate(self.paths):
                if self.isInterruptionRequested():
                    return
                self.progress.emit(index, len(self.paths), Path(path).name)
                self.inspected.emit(inspect_media(path, self.isInterruptionRequested))
            self.progress.emit(len(self.paths), len(self.paths), '')
        except ImportCancelled:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))
