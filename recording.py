"""Bounded, asynchronous WAV/MP3 recording; immutable format per recording."""
import json
import queue
import threading
import wave
import lameenc
import numpy as np
import soxr
from datetime import datetime
from pathlib import Path


MP3_BITRATES = (128, 192, 256, 320)
WAV_FORMATS = ((44100, 2), (48000, 2), (44100, 3), (48000, 3))


def estimated_mb_per_hour(format_name, bitrate=192, sample_rate=48000, sample_width=2):
    if format_name == 'WAV':
        return sample_rate * 2 * sample_width * 3600 / 1_000_000
    return bitrate * 1000 / 8 * 3600 / 1_000_000


def pcm24_to_pcm16(pcm):
    """Keep the most significant two bytes of signed little-endian L24."""
    result = bytearray(len(pcm) // 3 * 2)
    result[0::2], result[1::2] = pcm[1::3], pcm[2::3]
    return bytes(result)


def pcm_to_float(pcm, sample_width):
    if sample_width == 2:
        return np.frombuffer(pcm, dtype='<i2').reshape(-1, 2).astype(np.float32) / 32768
    data = np.frombuffer(pcm, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    values = data[:, 0] | data[:, 1] << 8 | data[:, 2] << 16
    values = (values ^ 0x800000) - 0x800000
    return values.reshape(-1, 2).astype(np.float32) / 8388608


def float_to_pcm(samples, sample_width):
    if sample_width == 2:
        return np.clip(np.rint(samples * 32768), -32768, 32767).astype('<i2').tobytes()
    values = np.clip(np.rint(samples * 8388608), -8388608, 8388607).astype('<i4').reshape(-1)
    packed = np.empty((len(values), 3), dtype=np.uint8)
    packed[:, 0] = values & 255
    packed[:, 1] = (values >> 8) & 255
    packed[:, 2] = (values >> 16) & 255
    return packed.tobytes()


class RecordingConverter:
    def __init__(self, sample_rate, input_width, output_width):
        self.sample_rate = sample_rate
        self.input_width = input_width
        self.output_width = output_width
        self.resampler = soxr.ResampleStream(48000, sample_rate, 2, dtype='float32') if sample_rate != 48000 else None

    def convert(self, pcm, last=False):
        if self.resampler:
            return float_to_pcm(self.resampler.resample_chunk(pcm_to_float(pcm, self.input_width), last=last), self.output_width)
        if self.output_width == self.input_width:
            return pcm
        if self.output_width == 2:
            return pcm24_to_pcm16(pcm)
        # Expanding a 16-bit fixture adds zero low bytes, never invented precision.
        result = bytearray(len(pcm) // 2 * 3)
        result[1::3], result[2::3] = pcm[0::2], pcm[1::2]
        return bytes(result)


class WavWriter:
    def __init__(self, stream, sample_rate, sample_width, input_width):
        self.sample_width = sample_width
        self.input_width = input_width
        self.converter = RecordingConverter(sample_rate, input_width, sample_width)
        self.wave = wave.open(stream, 'wb')
        self.wave.setparams((2, sample_width, sample_rate, 0, 'NONE', 'not compressed'))
        self.wave.writeframes(b'')
        self.frames = 0
        self.received_frames = 0

    def write(self, pcm):
        converted = self.converter.convert(pcm)
        self.received_frames += len(pcm) // (self.input_width * 2)
        self.wave.writeframesraw(converted)
        self.frames += len(converted) // (self.sample_width * 2)

    def close(self):
        try:
            if self.received_frames:
                converted = self.converter.convert(b'', last=True)
                self.wave.writeframesraw(converted)
                self.frames += len(converted) // (self.sample_width * 2)
        finally:
            # Release native resampler state before interpreter/Qt shutdown.
            self.converter.resampler = None
            self.wave.close()


class Mp3Writer:
    """Encode on the disk worker, batching small Livewire packets into MP3 frames."""
    def __init__(self, stream, bitrate, input_width):
        self.stream = stream
        self.input_width = input_width
        self.frames = 0
        self.encoder = lameenc.Encoder()
        self.encoder.set_channels(2)
        self.encoder.set_in_sample_rate(48000)
        self.encoder.set_out_sample_rate(48000)
        self.encoder.set_bit_rate(bitrate)
        self.encoder.set_vbr(0)  # explicit CBR, matching the size shown in the UI
        self.encoder.set_quality(2)
        self.encoder.silence()
        self.pending = bytearray()
        self.encoding = False

    def write(self, pcm):
        self.pending.extend(pcm24_to_pcm16(pcm) if self.input_width == 3 else pcm)
        self.frames += len(pcm) // (self.input_width * 2)
        if len(self.pending) >= 1152 * 4:
            self.encode_pending()

    def encode_pending(self):
        if self.pending:
            encoded = self.encoder.encode(bytes(self.pending))
            self.encoding = True
            self.pending.clear()
            if encoded:
                self.stream.write(encoded)

    def close(self):
        self.encode_pending()
        if self.encoding:
            self.stream.write(self.encoder.flush())
        self.encoder = None


class AudioRecorder:
    MAX_BYTES = 3_900_000_000

    def __init__(self, path, source, format_name='WAV', bitrate=192, sample_rate=48000, sample_width=2, input_width=2):
        if format_name not in ('WAV', 'MP3'):
            raise ValueError('Choose WAV or MP3.')
        if format_name == 'MP3' and bitrate not in MP3_BITRATES:
            raise ValueError('Choose an available MP3 bitrate.')
        if format_name == 'WAV' and (sample_rate, sample_width) not in WAV_FORMATS:
            raise ValueError('Choose an available WAV quality.')
        if input_width not in (2, 3):
            raise ValueError('Unsupported source sample width.')
        self.format_name = format_name
        self.bitrate = bitrate if format_name == 'MP3' else None
        self.sample_rate = sample_rate if format_name == 'WAV' else 48000
        self.sample_width = sample_width if format_name == 'WAV' else 2
        self.input_width = input_width
        self.path = Path(path)
        if self.path.suffix.lower() != '.' + format_name.lower():
            raise ValueError(f'The file extension must be .{format_name.lower()}.')
        self.source = dict(source)
        self.source['recording_format'] = (f'WAV PCM {sample_rate} Hz, stereo, {sample_width * 8}-bit' if format_name == 'WAV' else
            f'MP3 CBR {bitrate} kbps, 48000 Hz, stereo')
        self.started = datetime.now().astimezone().isoformat()
        self.reason = 'User stopped recording'
        self.input_format = (f'Stereo {input_width * 8}-bit PCM at 48000 Hz; '
            'Livewire RTP payload 96 is L24/48000/2')
        self.file = self.path.open('xb')
        try:
            self.writer = (WavWriter(self.file, sample_rate, sample_width, input_width)
                           if format_name == 'WAV' else Mp3Writer(self.file, bitrate, input_width))
        except Exception:
            self.file.close()
            raise
        self.input_frames = self.silence_frames = self.gaps = 0
        self.error = ''
        self.accepting = True
        self.finished = False
        self.last_timestamp = self.last_frames = None
        self.queue = queue.Queue(maxsize=4096)
        self.end_requested = threading.Event()
        self.thread = threading.Thread(target=self.run, name=f'Atlas {format_name} writer', daemon=True)
        self.thread.start()

    @property
    def frames(self):
        return self.writer.frames

    @property
    def duration_seconds(self):
        return self.input_frames / 48000

    @property
    def bit_rate_kbps(self):
        return self.bitrate if self.format_name == 'MP3' else self.sample_rate * self.sample_width * 8 * 2 / 1000

    def size_limit_reached(self, next_input_frames):
        if self.format_name == 'WAV':
            expected_frames = (self.input_frames + next_input_frames) * self.sample_rate / 48000
            return expected_frames * self.sample_width * 2 > self.MAX_BYTES
        return False

    def feed(self, pcm, timestamp):
        """Called only for accepted packets from the selected source."""
        if not self.accepting:
            return
        missing = 0
        if self.last_timestamp is not None:
            missing = (timestamp - self.last_timestamp - self.last_frames) & 0xffffffff
            if missing > 48000 * 10:
                self.fail('Stream timestamp discontinuity; recording stopped.')
                return
        frame_bytes = self.input_width * 2
        if len(pcm) % frame_bytes:
            self.fail('Unaligned audio samples; recording stopped.')
            return
        self.last_timestamp, self.last_frames = timestamp, len(pcm) // frame_bytes
        try:
            self.queue.put_nowait((pcm, missing))
        except queue.Full:
            self.fail('Recording storage could not keep up; recording stopped.')

    def fail(self, message):
        self.error = message
        self.accepting = False
        self.end_requested.set()

    def run(self):
        try:
            while not self.end_requested.is_set() or not self.queue.empty():
                try:
                    pcm, missing = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                frame_bytes = self.input_width * 2
                if self.size_limit_reached(missing + len(pcm) // frame_bytes):
                    self.fail('WAV size limit reached; recording stopped.')
                    break
                if missing:
                    self.writer.write(bytes(missing * frame_bytes))
                    self.input_frames += missing
                    self.silence_frames += missing
                    self.gaps += 1
                self.writer.write(pcm)
                self.input_frames += len(pcm) // frame_bytes
        except (OSError, wave.Error, RuntimeError) as exc:
            self.fail(f'Recording write failed: {exc}')
        finally:
            try:
                self.writer.close()
            except (OSError, wave.Error, RuntimeError) as exc:
                self.error = f'Could not finalize recording: {exc}'
            try:
                self.file.close()
            except OSError as exc:
                self.error = f'Could not close recording: {exc}'
            self.save_report()
            self.finished = True

    def save_report(self):
        report = dict(source=self.source, input_format=self.input_format, started=self.started,
            ended=datetime.now().astimezone().isoformat(), frames=self.frames,
            duration_seconds=self.duration_seconds, missing_audio_frames=self.silence_frames,
            input_frames=self.input_frames, input_sample_rate=48000,
            output_sample_rate=self.sample_rate, output_sample_width=self.sample_width,
            pcm_output_frames=self.frames, pcm_output_duration_seconds=self.frames / self.sample_rate,
            gap_intervals=self.gaps, error=self.error, stop_reason=self.reason,
            output_format=self.format_name, bitrate_kbps=self.bitrate,
            audio_bit_rate_kbps=self.bit_rate_kbps,
            expected_mb_per_hour=estimated_mb_per_hour(self.format_name, self.bitrate or 192, self.sample_rate, self.sample_width))
        try:
            # Exclusive sidecar creation preserves any pre-existing file too.
            with Path(str(self.path) + '.json').open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
        except OSError as exc:
            self.error = f'{self.error} Recording report could not be saved: {exc}'.strip()

    def stop(self, reason='User stopped recording'):
        self.reason = reason
        self.accepting = False
        self.end_requested.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            self.error = 'Storage is still finalizing the recording. Do not remove the recording drive.'
        return self.finished and not self.error


class WaveRecorder(AudioRecorder):
    def __init__(self, path, source, sample_rate=48000, sample_width=2, input_width=2):
        super().__init__(path, source, 'WAV', sample_rate=sample_rate, sample_width=sample_width, input_width=input_width)


class MP3Recorder(AudioRecorder):
    def __init__(self, path, source, bitrate=192, input_width=2):
        super().__init__(path, source, 'MP3', bitrate, input_width=input_width)
