"""Player acceptance: storage, full decoding and actual Qt GUI/decoder workflow.

Generated audio is test evidence only. Tests mute the output and inspect decoded
PCM; they do not certify acoustic output, AES67, or on-air continuity.
"""
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import lameenc
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QLineEdit

from broadcast_player.store import PlayerStore
from broadcast_player.media import inspect_media, availability, ImportCancelled
from broadcast_player.deck import LocalDeck
from broadcast_player.window import PlayerWindow


def make_wave(path, seconds=1.4, channels=2, rate=48000, width=2):
    t = np.arange(round(rate * seconds)) / rate
    samples = np.column_stack([.3 * np.sin(2 * np.pi * (997 if c == 0 else 1499) * t) for c in range(channels)])
    values = (samples * (2 ** (width * 8 - 1) - 1)).astype('<i4')
    if width == 3:
        pcm = values.view('u1').reshape(-1, 4)[:, :3].tobytes()
    else:
        pcm = values.astype('<i2').tobytes()
    with wave.open(str(path), 'wb') as output:
        output.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm)
    return samples


def make_mp3(path):
    t = np.arange(48000) / 48000
    samples = np.column_stack((.3 * np.sin(2 * np.pi * 997 * t), .15 * np.sin(2 * np.pi * 1499 * t)))
    encoder = lameenc.Encoder()
    encoder.set_in_sample_rate(48000)
    encoder.set_channels(2)
    encoder.set_bit_rate(192)
    path.write_bytes(bytes(encoder.encode((samples * 32767).astype('<i2').tobytes())) + bytes(encoder.flush()))


class PlayerMediaTests(unittest.TestCase):
    def test_supported_pcm_and_mp3_decode_actual_duration_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            for rate, channels, width in [(44100, 1, 2), (48000, 2, 2), (48000, 2, 3)]:
                path = Path(directory) / f'{rate}-{channels}-{width}.wav'
                make_wave(path, channels=channels, rate=rate, width=width)
                media = inspect_media(path)
                self.assertEqual(media['status'], 'ready', media)
                self.assertEqual((media['duration_ms'], media['sample_rate'], media['channels']), (1400, rate, channels))
            path = Path(directory) / 'джингл.mp3'
            make_mp3(path)
            media = inspect_media(path)
            self.assertEqual(media['status'], 'ready', media)
            self.assertAlmostEqual(media['duration_ms'], 1000, delta=100)
            self.assertEqual(media['channels'], 2)

    def test_corrupt_missing_empty_truncated_and_modified_media_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.wav'
            path.write_bytes(b'not a wave')
            self.assertEqual(inspect_media(path)['status'], 'invalid')
            self.assertEqual(inspect_media(Path(directory) / 'absent.wav')['error'], 'missing')
            make_wave(path, seconds=0)
            self.assertEqual(inspect_media(path)['status'], 'invalid')
            make_wave(path)
            media = inspect_media(path)
            path.write_bytes(path.read_bytes()[:10000])
            self.assertEqual(availability(media), 'changed')
            self.assertEqual(inspect_media(path)['status'], 'invalid')
            path.unlink()
            self.assertEqual(availability(media), 'missing')

    def test_import_can_be_cancelled_and_surround_does_not_downmix_implicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.wav'
            make_wave(path)
            with self.assertRaises(ImportCancelled):
                inspect_media(path, lambda: True)
            make_wave(path, channels=6)
            self.assertEqual(inspect_media(path)['error'], 'mono_stereo')

    def test_store_preserves_duplicates_queue_jingles_and_reimports_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.wav'
            make_wave(path)
            db = Path(directory) / 'state.sqlite3'
            store = PlayerStore(db)
            media_id = store.put_media(inspect_media(path))
            self.assertEqual(store.put_media(inspect_media(path)), media_id)
            self.assertEqual(len(store.library()), 1)
            store.save_playlist('Утро', [media_id, media_id])
            store.set_setting('queue', [media_id])
            store.assign_jingle(3, media_id)
            store.event('test', 'confirmed')
            store.close()
            store = PlayerStore(db)
            self.assertEqual(store.playlist('Утро'), [media_id, media_id])
            self.assertEqual(store.setting('queue'), [media_id])
            self.assertEqual(store.jingles(), {3: media_id})
            self.assertEqual(store.events()[0]['detail'], 'confirmed')
            with self.assertRaises(ValueError):
                store.save_playlist('broken', [99999])
            self.assertNotIn('broken', store.playlists())
            store.close()


class PlayerWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.first = self.directory / '01 Программа.wav'
        self.second = self.directory / '02 Джингл.mp3'
        make_wave(self.first, seconds=2.0)
        make_mp3(self.second)
        self.window = PlayerWindow(self.directory / 'state')
        self.window.show()
        self.window.volume.setValue(0)
        self.window.cue.set_volume(0)
        self.app.processEvents()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.requestInterruption()
            self.wait_for(lambda: self.window.worker is None)
        self.window.stop_queue()
        self.window.stop_cue()
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_for(self, condition, timeout=8000):
        start = time.monotonic()
        while time.monotonic() - start < timeout / 1000:
            self.app.processEvents()
            if condition():
                return
            QTest.qWait(15)
        self.fail('Timed out waiting for actual GUI/decoder state')

    def import_and_queue(self):
        with patch.object(QFileDialog, 'getOpenFileNames', return_value=([str(self.first), str(self.second)], '')):
            QTest.mouseClick(self.window.import_button, Qt.LeftButton)
        self.wait_for(lambda: self.window.worker is None)
        self.assertEqual(self.window.library.topLevelItemCount(), 2)
        self.window.library.selectAll()
        QTest.mouseClick(self.window.add_button, Qt.LeftButton)
        self.assertEqual(len(self.window.queue), 2)

    def choose_output(self):
        outputs = QMediaDevices.audioOutputs()
        if not outputs:
            self.skipTest('An audio output is required for real Qt playback verification')
        self.window.output.setCurrentIndex(1)
        self.window.cue_output.setCurrentIndex(1)

    def test_gui_import_edit_save_reopen_and_never_autoplay(self):
        self.import_and_queue()
        self.assertFalse(self.window.play.isEnabled())
        self.assertIsNone(self.window.output.currentData())
        self.window.queue_table.setCurrentItem(self.window.queue_table.topLevelItem(1))
        before = self.window.queue[:]
        QTest.mouseClick(self.window.up_button, Qt.LeftButton)
        self.assertEqual(self.window.queue, list(reversed(before)))
        with patch.object(QInputDialog, 'getText', return_value=('Утренний эфир', True)):
            QTest.mouseClick(self.window.save_button, Qt.LeftButton)
        self.assertEqual(self.window.store.playlist('Утренний эфир'), self.window.queue)
        self.window.library.clearSelection()
        self.window.library.topLevelItem(0).setSelected(True)
        QTest.mouseClick(self.window.jingle_buttons[0], Qt.LeftButton)
        self.assertIn(0, self.window.store.jingles())
        self.window.station.setText('Тестовая станция')
        self.window.close()
        self.window = PlayerWindow(self.directory / 'state')
        self.window.show()
        self.assertEqual(self.window.queue, list(reversed(before)))
        self.assertEqual(self.window.station.text(), 'Тестовая станция')
        self.assertIsNone(self.window.output.currentData())
        self.assertIsNone(self.window.cue_output.currentData())
        self.assertFalse(self.window.running)
        self.assertIsNone(self.window.deck.sink)
        self.assertEqual(self.window.lang, 'ru')
        self.window.station.setText('Название перед сменой языка')
        self.window.language.setCurrentIndex(1)
        self.assertEqual(self.window.play.text(), '▶  Start')
        self.assertEqual(self.window.station.text(), 'Название перед сменой языка')
        self.assertEqual(self.window.queue, list(reversed(before)))

    def test_real_file_dialog_accepts_files_with_spaces_and_cyrillic(self):
        observed = []
        def choose():
            dialog = self.app.activeModalWidget()
            if not isinstance(dialog, QFileDialog):
                return
            observed.append(dialog.testOption(QFileDialog.DontUseNativeDialog))
            edit = dialog.findChild(QLineEdit, 'fileNameEdit')
            edit.setText(f'"{self.first}" "{self.second}"')
            QTest.keyClick(edit, Qt.Key_Return)
        QTimer.singleShot(100, choose)
        # Bound a failed dialog test rather than leaving a modal blocking CI.
        escape = QTimer()
        escape.setSingleShot(True)
        escape.timeout.connect(lambda: self.app.activeModalWidget().reject() if self.app.activeModalWidget() else None)
        escape.start(5000)
        self.window.choose_files()
        escape.stop()
        self.wait_for(lambda: self.window.worker is None)
        self.assertEqual(observed, [True])
        self.assertEqual(self.window.library.topLevelItemCount(), 2)
        self.assertTrue(all(row['status'] == 'ready' for row in self.window.store.library()))

    def test_real_queue_decode_transition_pause_stop_and_channel_integrity(self):
        self.import_and_queue()
        self.choose_output()
        chunks = []
        self.window.deck.decoded.connect(lambda samples: chunks.append(samples))
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.wait_for(lambda: self.window.deck.state == 'playing' and len(chunks) >= 2)
        self.assertFalse(self.window.output.isEnabled())
        QTest.mouseClick(self.window.pause, Qt.LeftButton)
        self.wait_for(lambda: self.window.deck.state == 'paused')
        self.assertEqual(self.window.pause.text(), 'Продолжить')
        QTest.mouseClick(self.window.pause, Qt.LeftButton)
        self.wait_for(lambda: not self.window.running, 12000)
        actions = [e['action'] for e in self.window.store.events()]
        self.assertEqual(actions.count('started'), 2)
        self.assertEqual(actions.count('completed'), 2)
        self.assertNotIn('error', actions)
        samples = np.concatenate(chunks)
        self.assertTrue(np.isfinite(samples).all())
        self.assertEqual(samples.shape[1], 2)
        self.assertGreater(np.max(np.abs(samples[:, 0])), .25)
        # Inspect the first WAV segment before the MP3 transition.
        section = samples[3000:35000]
        bins = np.fft.rfftfreq(len(section), 1 / self.window.deck.sample_rate)
        fft = np.abs(np.fft.rfft(section * np.hanning(len(section))[:, None], axis=0))
        self.assertAlmostEqual(bins[np.argmax(fft[:, 0])], 997, delta=3)
        self.assertAlmostEqual(bins[np.argmax(fft[:, 1])], 1499, delta=3)
        self.assertFalse(self.window.deck.active)

    def test_missing_and_changed_files_block_start_without_skipping(self):
        self.import_and_queue()
        self.choose_output()
        self.second.unlink()
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.assertFalse(self.window.running)
        self.assertIsNone(self.window.deck.sink)
        self.assertIn('не найден', self.window.notice.text())
        self.first.write_bytes(self.first.read_bytes() + b'changed')
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.assertIn('изменился', self.window.notice.text())

    def test_lost_output_and_file_removed_between_tracks_stop_queue(self):
        self.import_and_queue()
        self.choose_output()
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.wait_for(lambda: self.window.deck.state == 'playing')
        with patch('broadcast_player.playout.QMediaDevices.audioOutputs', return_value=[]):
            self.window.deck.check_device()
        self.assertFalse(self.window.running)
        self.assertEqual(self.window.deck.state, 'error')
        self.assertIsNone(self.window.deck.sink)
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.wait_for(lambda: self.window.deck.state == 'playing')
        self.second.unlink()
        self.wait_for(lambda: not self.window.running)
        self.assertEqual(self.window.deck.state, 'error')
        self.assertIn('не найден', self.window.notice.text())
        self.assertEqual(sum(e['action'] == 'completed' for e in self.window.store.events()), 1)

    def test_stop_after_current_and_cue_do_not_mix_into_shared_output(self):
        self.import_and_queue()
        self.choose_output()
        self.window.stop_after.setChecked(True)
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.wait_for(lambda: self.window.deck.state == 'playing')
        self.window.preview_selected()
        self.assertFalse(self.window.cue.active)
        self.assertIn('один выход', self.window.notice.text())
        self.wait_for(lambda: not self.window.running)
        self.assertEqual(sum(e['action'] == 'completed' for e in self.window.store.events()), 1)
        chunks = []
        self.window.cue.decoded.connect(lambda x: chunks.append(x))
        self.window.preview_selected()
        self.wait_for(lambda: bool(chunks))
        self.assertTrue(self.window.cue.active)
        QTest.mouseClick(self.window.cue_stop, Qt.LeftButton)
        self.assertFalse(self.window.cue.active)

    def test_stop_cancels_preparation_and_pending_next_item(self):
        self.import_and_queue()
        self.choose_output()
        self.window.start_queue()
        self.wait_for(lambda: self.window.deck.state == 'playing')
        self.window.stop_queue()
        QTest.qWait(300)
        self.window.deck.pump()
        self.assertIsNone(self.window.deck.sink)
        self.assertFalse(self.window.running)
        self.assertEqual(sum(e['action'] == 'started' for e in self.window.store.events()), 1)
        self.window.start_queue()
        self.window.stop_queue()  # Cancel while background preparation is pending.
        QTest.qWait(300)
        self.window.deck.pump()
        self.assertEqual(self.window.deck.state, 'stopped')
        self.assertFalse(self.window.deck.jobs)

    def test_jingle_keyboard_and_preview_complete_without_starting_queue(self):
        self.import_and_queue()
        self.choose_output()
        self.window.library.clearSelection()
        self.window.library.topLevelItem(1).setSelected(True)
        self.window.assign_jingle(0)
        self.window.activateWindow()
        self.window.setFocus()
        QTest.qWait(100)
        QTest.keyClick(self.window, Qt.Key_1, Qt.ControlModifier)
        self.wait_for(lambda: self.window.cue.state == 'playing')
        self.assertFalse(self.window.running)
        self.wait_for(lambda: not self.window.cue.active)
        self.assertIn('cue_completed', [e['action'] for e in self.window.store.events()])


if __name__ == '__main__':
    unittest.main()
