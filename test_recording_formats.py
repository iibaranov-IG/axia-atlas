import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from audio_monitor import AudioBuffer, CompactPlayer, decode_rtp
from recording import (WaveRecorder, MP3Recorder, MP3_BITRATES, WAV_FORMATS,
                       estimated_mb_per_hour, float_to_pcm, pcm_to_float)


def stereo_test_signal(seconds=2):
    t = np.arange(int(seconds * 48000), dtype=np.float64) / 48000
    samples = np.column_stack((.4 * np.sin(2 * np.pi * 997 * t),
                               .2 * np.sin(2 * np.pi * 1499 * t))).astype(np.float32)
    return float_to_pcm(samples, 3)


def record_pcm(recorder, pcm, width=3):
    for frame in range(0, len(pcm) // (2 * width), 480):
        recorder.feed(pcm[frame * 2 * width:(frame + 480) * 2 * width], frame)
    return recorder.stop()


def channel_frequencies(samples, rate):
    # Use the center to exclude encoder delay and resampling boundaries.
    center = samples[rate // 4:-rate // 4]
    windowed = center * np.hanning(len(center))[:, None]
    fft = np.abs(np.fft.rfft(windowed, axis=0))
    frequencies = np.fft.rfftfreq(len(center), 1 / rate)
    return [frequencies[np.argmax(fft[:, channel])] for channel in (0, 1)]


class RecordingFormatTests(unittest.TestCase):
    def test_native_24_bit_rtp_is_preserved_bit_for_bit_in_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.wav'
            recorder = WaveRecorder(path, {'channel': 1301}, sample_width=3, input_width=3)
            buffer = AudioBuffer(enforce_ssrc=False)
            buffer.recorder = recorder
            values = [(8388607, -8388608), (1, -1), (1193046, -1193047), (255, -256)]
            expected = b''
            for index, pair in enumerate(values):
                payload = b''.join(value.to_bytes(3, 'big', signed=True) for value in pair)
                packet = struct.pack('!BBHII', 0x80, 96, index, index, index + 1) + payload
                expected += b''.join(value.to_bytes(3, 'little', signed=True) for value in pair)
                buffer.feed(packet)
            self.assertTrue(recorder.stop())
            with wave.open(str(path), 'rb') as result:
                self.assertEqual(result.getparams()[:4], (2, 3, 48000, len(values)))
                self.assertEqual(result.readframes(len(values)), expected)
            self.assertEqual(recorder.input_width, 3)
            self.assertEqual(recorder.bit_rate_kbps, 2304)
            self.assertEqual(recorder.duration_seconds, len(values) / 48000)

    def test_all_wav_qualities_have_correct_headers_duration_and_stereo(self):
        with tempfile.TemporaryDirectory() as directory:
            source = stereo_test_signal()
            for sample_rate, sample_width in WAV_FORMATS:
                with self.subTest(rate=sample_rate, width=sample_width):
                    path = Path(directory) / f'{sample_rate}_{sample_width}.wav'
                    recorder = WaveRecorder(path, {}, sample_rate, sample_width, input_width=3)
                    self.assertTrue(record_pcm(recorder, source), recorder.error)
                    with wave.open(str(path), 'rb') as result:
                        params = result.getparams()
                        samples = pcm_to_float(result.readframes(result.getnframes()), sample_width)
                    self.assertEqual(params[:4], (2, sample_width, sample_rate, sample_rate * 2))
                    frequencies = channel_frequencies(samples, sample_rate)
                    self.assertAlmostEqual(frequencies[0], 997, delta=1)
                    self.assertAlmostEqual(frequencies[1], 1499, delta=1)
                    rms = np.sqrt(np.mean(samples[sample_rate // 4:-sample_rate // 4] ** 2, axis=0))
                    self.assertAlmostEqual(rms[0], .4 / np.sqrt(2), delta=.002)
                    self.assertAlmostEqual(rms[1], .2 / np.sqrt(2), delta=.002)
                    if sample_width == 3 and sample_rate == 48000:
                        with wave.open(str(path), 'rb') as result:
                            self.assertEqual(result.readframes(result.getnframes()), source)
                    report = json.loads(Path(str(path) + '.json').read_text())
                    self.assertEqual(report['frames'], params.nframes)
                    self.assertEqual(report['duration_seconds'], 2.0)
                    self.assertEqual(report['pcm_output_duration_seconds'], 2.0)
                    self.assertAlmostEqual(report['expected_mb_per_hour'], path.stat().st_size / 2 * 3600 / 1e6, delta=.09)
                    self.assertEqual(report['audio_bit_rate_kbps'], sample_rate * sample_width * 16 / 1000)

    def test_empty_44k_24_bit_wav_and_invalid_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.wav'
            recorder = WaveRecorder(path, {}, 44100, 3, input_width=3)
            self.assertTrue(recorder.stop())
            with wave.open(str(path), 'rb') as result:
                self.assertEqual(result.getparams()[:4], (2, 3, 44100, 0))
            for sample_rate, sample_width in ((96000, 3), (48000, 4), (44100, 1)):
                with self.assertRaises(ValueError):
                    WaveRecorder(Path(directory) / 'invalid.wav', {}, sample_rate, sample_width)
            self.assertFalse((Path(directory) / 'invalid.wav').exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Independent MP3 decoder required for verification only')
    def test_every_mp3_bitrate_decodes_to_correct_channels_and_frequency(self):
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        source = stereo_test_signal()
        sizes = []
        with tempfile.TemporaryDirectory() as directory:
            for bitrate in MP3_BITRATES:
                with self.subTest(bitrate=bitrate):
                    path = Path(directory) / f'{bitrate}.mp3'
                    recorder = MP3Recorder(path, {'channel': 1301}, bitrate=bitrate, input_width=3)
                    self.assertTrue(record_pcm(recorder, source), recorder.error)
                    probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-show_entries',
                        'stream=codec_name,sample_rate,channels,bit_rate,duration', '-of', 'json', str(path)],
                        capture_output=True, check=True, timeout=10, creationflags=flags)
                    stream = json.loads(probe.stdout)['streams'][0]
                    self.assertEqual(stream['codec_name'], 'mp3')
                    self.assertEqual(int(stream['sample_rate']), 48000)
                    self.assertEqual(stream['channels'], 2)
                    self.assertEqual(int(stream['bit_rate']), bitrate * 1000)
                    self.assertAlmostEqual(float(stream['duration']), 2, delta=.1)
                    decoded = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(path),
                        '-map', '0:a:0', '-ac', '2', '-ar', '48000', '-f', 'f32le', '-c:a', 'pcm_f32le', 'pipe:1'],
                        capture_output=True, check=True, timeout=10, creationflags=flags)
                    samples = np.frombuffer(decoded.stdout, dtype='<f4').reshape(-1, 2)
                    self.assertGreaterEqual(len(samples), 96000)
                    self.assertLess(len(samples), 100800)
                    frequencies = channel_frequencies(samples, 48000)
                    self.assertAlmostEqual(frequencies[0], 997, delta=2)
                    self.assertAlmostEqual(frequencies[1], 1499, delta=2)
                    rms = np.sqrt(np.mean(samples[12000:-12000] ** 2, axis=0))
                    self.assertGreater(rms[0], .25)
                    self.assertLess(rms[0], .30)
                    self.assertGreater(rms[1], .12)
                    self.assertLess(rms[1], .16)
                    self.assertTrue(np.isfinite(samples).all())
                    self.assertGreater(path.stat().st_size, bitrate * 1000 / 8 * 2)
                    self.assertLess(path.stat().st_size, bitrate * 1000 / 8 * 2.1)
                    sizes.append(path.stat().st_size)
                    report = json.loads(Path(str(path) + '.json').read_text())
                    self.assertEqual(report['output_format'], 'MP3')
                    self.assertEqual(report['bitrate_kbps'], bitrate)
                    self.assertEqual(report['input_frames'], 96000)
                    self.assertEqual(report['duration_seconds'], 2.0)
                    self.assertEqual(report['expected_mb_per_hour'], bitrate * .45)
                    self.assertEqual(report['source']['channel'], 1301)
            self.assertEqual(sorted(sizes), sizes)
            self.assertAlmostEqual(sizes[-1] / sizes[0], 320 / 128, delta=.1)

    def test_mp3_format_validation_no_overwrite_and_empty_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.mp3'
            recorder = MP3Recorder(path, {}, 192, input_width=3)
            self.assertTrue(recorder.stop())
            self.assertEqual(path.stat().st_size, 0)
            self.assertEqual(recorder.frames, 0)
            with self.assertRaises(FileExistsError):
                MP3Recorder(path, {}, 128)
            with self.assertRaises(ValueError):
                MP3Recorder(Path(directory) / 'invalid.mp3', {}, 999)
            with self.assertRaises(ValueError):
                MP3Recorder(Path(directory) / 'wrong.wav', {}, 192)
            self.assertFalse((Path(directory) / 'wrong.wav').exists())

    def test_quality_ui_size_filename_persistence_and_controls_locked_while_recording(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.IniFormat)
            player = CompactPlayer(lambda: None, settings)
            player.show()
            source = dict(ip='192.0.2.1', name='Test Studio', channel=1301,
                          slot=1, multicast='239.192.5.21', channels=2)
            player.select(source)
            player.receiver = MagicMock()
            player.receiver.buffer = AudioBuffer()
            for sample_rate, sample_width in WAV_FORMATS:
                player.record_format.setCurrentText('WAV')
                for index in range(player.wav_quality.count()):
                    if player.wav_quality.itemData(index) == [sample_rate, sample_width]:
                        player.wav_quality.setCurrentIndex(index)
                self.assertIn(f'{estimated_mb_per_hour("WAV", sample_rate=sample_rate, sample_width=sample_width):.1f}', player.record_size.text())
                self.assertTrue(player.wav_quality.isVisible())
                self.assertFalse(player.record_bitrate.isVisible())
            player.record_format.setCurrentText('MP3')
            self.assertFalse(player.wav_quality.isVisible())
            self.assertTrue(player.record_bitrate.isVisible())
            for bitrate in MP3_BITRATES:
                player.record_bitrate.setCurrentIndex(player.record_bitrate.findData(bitrate))
                self.assertIn(f'{bitrate * .45:.1f}', player.record_size.text())
            path = Path(directory) / 'selected.mp3'
            with patch('audio_monitor.QFileDialog.getSaveFileName', return_value=(str(path.with_suffix('')), 'MP3 audio (*.mp3)')) as dialog:
                QTest.mouseClick(player.record_button, Qt.LeftButton)
                self.assertTrue(dialog.call_args.args[2].endswith('.mp3'))
                self.assertEqual(dialog.call_args.args[3], 'MP3 audio (*.mp3)')
            self.assertEqual(player.recorder.format_name, 'MP3')
            self.assertEqual(player.recorder.bitrate, 320)
            self.assertFalse(player.record_format.isEnabled())
            self.assertFalse(player.record_bitrate.isEnabled())
            with player.receiver.buffer.lock:
                player.recorder.feed(stereo_test_signal(.1), 0)
            QTest.mouseClick(player.record_button, Qt.LeftButton)
            self.assertTrue(player.record_format.isEnabled())
            self.assertTrue(player.record_bitrate.isEnabled())
            self.assertTrue(path.exists())
            player.stop()
            player.close()
            app.processEvents()
            restored = CompactPlayer(lambda: None, settings)
            self.assertEqual(restored.record_format.currentText(), 'MP3')
            self.assertEqual(restored.record_bitrate.currentData(), 320)
            self.assertEqual(restored.wav_quality.currentData(), [48000, 3])
            self.assertEqual(settings.value('recording_folder'), str(Path(directory).resolve()))
            restored.record_format.setCurrentText('WAV')
            self.assertIn('2304 kbps', restored.record_size.text())
            restored.close()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
