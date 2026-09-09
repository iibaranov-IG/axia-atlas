import json
import struct
import tempfile
import unittest
import time
from types import SimpleNamespace
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QUdpSocket, QHostAddress
from audio_monitor import decode_rtp, AudioBuffer, OutputConverter, CompactPlayer, AudioSourceList
from PySide6.QtMultimedia import QAudioFormat, QAudio
import numpy as np
from events import EventsPanel, parse_syslog


def packet(seq=1, timestamp=0, ssrc=9):
    return struct.pack('!BBHII', 0x80, 96, seq, timestamp, ssrc) + b'\x7f\xff\xff\x80\x00\x00'


class AudioEventsTests(unittest.TestCase):
    def test_audio_list_excludes_disabled_sources_after_refresh(self):
        app = QApplication.instance() or QApplication([])
        settings = SimpleNamespace(value=lambda *args, **kwargs: [])
        panel = AudioSourceList(settings)
        sources = [dict(slot=i, channel=100+i, name=f'Source {i}', multicast=f'239.192.0.{i}', enabled=i==1) for i in (1,2)]
        device = dict(ip='192.0.2.1', name='Fixture', sources=sources)
        panel.update_device(device)
        self.assertEqual(panel.tree.topLevelItemCount(), 1)
        self.assertEqual(next(iter(panel.sources.values()))['channel'], 101)
        sources[0]['enabled'] = False
        panel.update_device(device)
        self.assertEqual(panel.tree.topLevelItemCount(), 0)
        self.assertEqual(panel.sources, {})
        panel.close()

    def test_output_prefills_and_releases_receiver_lock_before_conversion(self):
        app = QApplication.instance() or QApplication([])
        player = CompactPlayer(lambda: None)
        buffer = AudioBuffer()
        buffer.last_packet = time.monotonic()
        player.receiver = SimpleNamespace(buffer=buffer)
        player.sink = SimpleNamespace(bytesFree=lambda: 50000, error=lambda: QAudio.NoError)
        writes = []
        player.writer = SimpleNamespace(write=lambda data: writes.append(data) or len(data))
        player.output_format = QAudioFormat()
        player.output_format.setSampleRate(48000)
        player.output_format.setChannelCount(2)
        player.output_format.setSampleFormat(QAudioFormat.Int16)
        player.prefilled = player.in_dropout = False
        player.last_ui = time.monotonic()
        def convert(data):
            self.assertTrue(buffer.lock.acquire(blocking=False))
            buffer.lock.release()
            return data
        player.converter = SimpleNamespace(convert=convert)
        try:
            buffer.pcm.extend(bytes(19008))  # 99 ms must stay queued
            player.pump()
            self.assertEqual(writes, [])
            buffer.pcm.extend(bytes(192))
            player.pump()
            self.assertEqual(len(writes[0]), 19200)
            self.assertEqual(len(buffer.pcm), 0)
        finally:
            player.receiver = player.sink = player.converter = None
            player.close()

    def test_stateful_resampling_preserves_duration_and_stereo(self):
        converter = OutputConverter(44100, QAudioFormat.Float)
        samples = np.empty((48000, 2), dtype='<i2')
        samples[:, 0] = 8192
        samples[:, 1] = -16384
        chunks = [converter.convert(samples[i:i+480].tobytes(), last=i == 47520)
                  for i in range(0, 48000, 480)]
        result = np.frombuffer(b''.join(chunks), dtype='<f4').reshape(-1, 2)
        self.assertEqual(len(result), 44100)
        self.assertTrue(np.allclose(result[1000:-1000, 0], .25, atol=.001))
        self.assertTrue(np.allclose(result[1000:-1000, 1], -.5, atol=.001))

    def test_legacy_livewire_variable_header(self):
        buffer = AudioBuffer(enforce_ssrc=False)
        buffer.feed(packet(1, 0, 9))
        buffer.feed(packet(2, 1, 10))
        self.assertEqual(buffer.packets, 2)
        self.assertEqual(buffer.foreign, 0)

    def test_pcm_endianness_sequence_wrap_and_foreign_stream(self):
        self.assertEqual(decode_rtp(packet())[3], b'\xff\x7f\x00\x80')
        buffer = AudioBuffer()
        buffer.feed(packet(65535))
        buffer.feed(packet(0, 1))
        buffer.feed(packet(0, 1))
        buffer.feed(packet(1, 2, 10))
        self.assertEqual(buffer.packets, 2)
        self.assertEqual(buffer.gaps, 0)
        self.assertEqual(buffer.late, 1)
        self.assertEqual(buffer.foreign, 1)
        self.assertLessEqual(buffer.left, 0)
        with self.assertRaises(ValueError):
            decode_rtp(b'not an audio packet')

    def test_real_udp_device_event_and_application_filter_archive(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            panel = EventsPanel(directory)
            panel.show()
            panel.appendPlainText('Application verification event')
            self.assertTrue(panel.start_receiver('127.0.0.1', 0))
            port = panel.socket.localPort()
            sender = QUdpSocket()
            raw = b'<132>Sep 9 12:00:00 test-node Warning fixture'
            sender.writeDatagram(raw, QHostAddress.LocalHost, port)
            loop = QEventLoop()
            QTimer.singleShot(100, loop.quit)
            loop.exec()
            self.assertEqual(panel.received, 1)
            self.assertEqual(panel.records[-1]['severity'], 'Warning')
            self.assertEqual(panel.records[-1]['raw_hex'], raw.hex())
            panel.origin.setCurrentText('Devices')
            self.assertTrue(panel.tree.topLevelItem(0).isHidden())
            self.assertFalse(panel.tree.topLevelItem(1).isHidden())
            archived = [json.loads(line) for path in Path(directory).glob('*.jsonl') for line in path.read_text().splitlines()]
            self.assertEqual(len(archived), 2)
            self.assertEqual(archived[1]['ip'], '127.0.0.1')
            panel.stop_receiver()
            panel.close()
            app.processEvents()

    def test_unstructured_syslog_is_preserved(self):
        record = parse_syslog(b'raw\xffmessage')
        self.assertEqual(record['severity'], 'Unknown')
        self.assertEqual(bytes.fromhex(record['raw_hex']), b'raw\xffmessage')
