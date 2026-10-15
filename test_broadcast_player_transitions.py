"""Measure the real mixer PCM; Qt tests also exercise one actual output sink."""
import tempfile
import time
import json
import os
import wave
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from broadcast_player.media import inspect_media
from broadcast_player.pcm import PreparedAudio, PcmSequence, PlayoutError, prepare_audio
import test_broadcast_player as player_tests
from test_broadcast_player import make_wave


class MixerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.tracks = []

    def tearDown(self):
        for track in self.tracks:
            track.close()
        self.temp.cleanup()

    def track(self, samples):
        path = self.directory / f'{len(self.tracks)}.wav'
        make_wave(path, seconds=len(samples) / 48000)
        file = tempfile.TemporaryFile(dir=self.directory)
        file.write(np.asarray(samples, dtype='<f4').tobytes())
        file.flush()
        track = PreparedAudio(file, len(samples), 48000, inspect_media(path))
        self.tracks.append(track)
        return track

    def render(self, sequence, block=137):
        chunks = []
        for _ in range(50000):
            chunk = sequence.read(block)
            if len(chunk):
                chunks.append(chunk)
            if sequence.finished:
                return np.concatenate(chunks)
        self.fail('Mixer did not terminate')

    def test_exact_crossfade_samples_duration_stereo_and_chunk_independence(self):
        a = np.tile([.8, -.6], (48000, 1)).astype('<f4')
        b = np.tile([-.2, .4], (72000, 1)).astype('<f4')
        self.track(a)
        self.track(b)
        expected = np.concatenate((a[:-24000],
            (a[-24000:] * (1 - np.linspace(0, 1, 24000)[:, None]) +
             b[:24000] * np.linspace(0, 1, 24000)[:, None]).astype('<f4'), b[24000:]))
        for block in (137, 4096, 200000):
            seq = PcmSequence(self.tracks.__getitem__, 2, 0, 48000, 500)
            actual = self.render(seq, block)
            self.assertEqual(actual.shape, (96000, 2))
            np.testing.assert_allclose(actual, expected, atol=1e-7)
            self.assertEqual(seq.events, [(0, 'started', 0, 0), (24000, 'started', 1, 0),
                (24000, 'transition', 1, 24000), (48000, 'completed', 0, 0),
                (96000, 'completed', 1, 0)])
            self.assertLessEqual(float(abs(actual).max()), .81)

    def test_no_overlap_adds_no_samples_and_preserves_authored_silence(self):
        a = np.tile([.25, -.25], (2400, 1)).astype('<f4')
        a[-100:] = 0
        b = np.tile([.5, .75], (4000, 1)).astype('<f4')
        self.track(a)
        self.track(b)
        seq = PcmSequence(self.tracks.__getitem__, 2, 0, 48000)
        np.testing.assert_array_equal(self.render(seq), np.concatenate((a, b)))

    def test_short_three_item_chain_has_no_triple_overlap_or_gain_bump(self):
        lengths = (4800, 2400, 3600)
        for length in lengths:
            self.track(np.tile([.9, -.9], (length, 1)))
        seq = PcmSequence(self.tracks.__getitem__, 3, 0, 48000, 10000)
        actual = self.render(seq)
        self.assertEqual(len(actual), sum(lengths) - 1200 - 1200)
        np.testing.assert_allclose(actual, np.tile([.9, -.9], (len(actual), 1)), atol=1e-7)
        self.assertEqual(sum(event[1] == 'completed' for event in seq.events), 3)

    def test_stop_after_current_preserves_entire_tail_without_starting_next(self):
        a = np.tile([.6, .4], (24000, 1)).astype('<f4')
        self.track(a)
        self.track(-a)
        seq = PcmSequence(self.tracks.__getitem__, 2, 0, 48000, 300, stop_at=0)
        np.testing.assert_array_equal(self.render(seq), a)
        self.assertEqual(seq.events, [(0, 'started', 0, 0), (24000, 'completed', 0, 0)])

    def test_missing_or_unprepared_next_finishes_current_dry_and_reports_error(self):
        a = np.tile([.6, .4], (24000, 1)).astype('<f4')
        self.track(a)
        second = self.track(a)
        Path(second.item['path']).unlink()
        seq = PcmSequence(self.tracks.__getitem__, 2, 0, 48000, 300)
        np.testing.assert_array_equal(self.render(seq), a)
        self.assertEqual(seq.error, 'missing')
        def provider(index):
            if index:
                raise PlayoutError('not_prepared')
            return self.tracks[0]
        seq = PcmSequence(provider, 2, 0, 48000, 300)
        np.testing.assert_array_equal(self.render(seq), a)
        self.assertEqual(seq.error, 'not_prepared')

    def test_real_mono_resampling_preserves_level_and_cancellation_cleans_cache(self):
        path = self.directory / 'mono.wav'
        make_wave(path, seconds=1, channels=1, rate=44100)
        cache = self.directory / 'cache'
        track = prepare_audio(inspect_media(path), 48000, cache, Event())
        self.tracks.append(track)
        self.assertEqual(track.frames, 48000)
        samples = track.read(0, track.frames)
        np.testing.assert_array_equal(samples[:, 0], samples[:, 1])
        self.assertAlmostEqual(float(abs(samples).max()), .3, places=3)
        track.close()
        cancelled = Event()
        cancelled.set()
        with self.assertRaisesRegex(PlayoutError, 'cancelled'):
            prepare_audio(inspect_media(path), 48000, cache, cancelled)
        self.assertEqual(list(cache.iterdir()), [])

    def test_seek_near_end_limits_fade_to_remaining_tail(self):
        a = np.tile([.6, .4], (24000, 1)).astype('<f4')
        self.track(a)
        self.track(-a)
        seq = PcmSequence(self.tracks.__getitem__, 2, 0, 48000, 1000, offset=22000, announce=False)
        actual = self.render(seq)
        self.assertEqual(len(actual), 2000 + 24000 - 1000)
        self.assertEqual(seq.events[0], (1000, 'started', 1, 0))

    def test_late_cancellation_of_stop_uses_only_remaining_samples(self):
        a = np.tile([.6, .4], (24000, 1)).astype('<f4')
        self.track(a)
        self.track(-a)
        seq = PcmSequence(self.tracks.__getitem__, 2, 0, 48000, 1000, stop_at=0)
        head = seq.read(22000)
        seq.stop_at, seq.plan = None, None
        tail = self.render(seq)
        self.assertEqual(len(head) + len(tail), 48000 - 2000)
        self.assertIn((22000, 'transition', 1, 2000), seq.events)
        np.testing.assert_allclose(tail[1999], [-.6, -.4], atol=1e-7)


# Reuse setup/helpers without running inherited tests twice.
class TransitionWorkflowTests(unittest.TestCase):
    setUpClass = classmethod(player_tests.PlayerWorkflowTests.setUpClass.__func__)
    setUp = player_tests.PlayerWorkflowTests.setUp
    tearDown = player_tests.PlayerWorkflowTests.tearDown
    wait_for = player_tests.PlayerWorkflowTests.wait_for
    import_and_queue = player_tests.PlayerWorkflowTests.import_and_queue
    choose_output = player_tests.PlayerWorkflowTests.choose_output

    def test_crossfade_uses_one_output_and_measured_pcm_matches_reference(self):
        self.import_and_queue()
        self.choose_output()
        self.window.crossfade.setValue(.5)
        chunks, sinks, transitions = [], [], []
        self.window.deck.decoded.connect(lambda x: chunks.append(x))
        self.window.deck.started.connect(lambda _: sinks.append(self.window.deck.sink))
        self.window.deck.transition.connect(lambda i, ms: transitions.append((i, ms)))
        QTest.mouseClick(self.window.play, Qt.LeftButton)
        self.wait_for(lambda: self.window.deck.state == 'playing')
        rate = self.window.deck.sample_rate
        self.assertIn(self.window.deck.next_state, ('ready', ''))
        self.assertFalse(self.window.crossfade.isEnabled())
        self.wait_for(lambda: not self.window.running, 12000)
        self.assertEqual(len(sinks), 2)
        self.assertIs(sinks[0], sinks[1])
        self.assertEqual(transitions, [(1, 500)])
        tracks = [prepare_audio(inspect_media(path), rate, self.directory / 'expected', Event())
                  for path in (self.first, self.second)]
        try:
            seq = PcmSequence(tracks.__getitem__, 2, 0, rate, 500)
            expected = []
            while not seq.finished:
                expected.append(seq.read(4096))
            actual = np.concatenate(chunks)
            reference = np.clip(np.concatenate(expected), -1, 1)
            np.testing.assert_allclose(actual, reference, atol=1e-7)
            if os.environ.get('ATLAS_PLAYER_EVIDENCE_DIR'):
                evidence = Path(os.environ['ATLAS_PLAYER_EVIDENCE_DIR'])
                evidence.mkdir(parents=True, exist_ok=True)
                with wave.open(str(evidence / 'accepted-output.wav'), 'wb') as output:
                    output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
                    output.writeframes(np.round(actual * 32767).astype('<i2').tobytes())
                (evidence / 'result.json').write_text(json.dumps({
                    'output': self.window.deck.device.description(), 'rate': rate,
                    'frames': len(actual), 'duration_seconds': len(actual) / rate,
                    'crossfade_ms': 500, 'output_instances': len({id(sink) for sink in sinks}),
                    'max_sample_error': float(np.max(np.abs(actual - reference))),
                    'capture_point': 'PCM accepted by QAudioSink, before muted output volume',
                    'acoustic_output_verified': False,
                }, ensure_ascii=False, indent=2), encoding='utf-8')
                self.window.grab().save(str(evidence / 'player-ru.png'))
                self.window.language.setCurrentIndex(1)
                self.app.processEvents()
                self.window.grab().save(str(evidence / 'player-en.png'))
        finally:
            for track in tracks:
                track.close()
        self.assertNotIn('error', [e['action'] for e in self.window.store.events()])
        self.assertEqual(self.window.store.setting('crossfade_ms'), 500)

    def test_seek_while_paused_then_stop_after_current(self):
        self.import_and_queue()
        self.choose_output()
        self.window.crossfade.setValue(.5)
        self.window.start_queue()
        self.wait_for(lambda: self.window.deck.state == 'playing')
        self.window.deck.toggle_pause()
        self.window.deck.seek(1000)
        self.wait_for(lambda: self.window.deck.state == 'paused')
        self.assertFalse(self.window.deck.announce)
        QTest.qWait(800)  # An operator pause must not count as a missed feed deadline.
        self.window.stop_after.setChecked(True)
        self.window.deck.toggle_pause()
        self.wait_for(lambda: not self.window.running)
        actions = [e['action'] for e in self.window.store.events()]
        self.assertEqual(actions.count('started'), 1)
        self.assertEqual(actions.count('completed'), 1)
        self.assertNotIn('transition', actions)

    def test_skip_during_crossfade_discards_pending_tail_and_never_false_completes(self):
        self.import_and_queue()
        self.choose_output()
        self.window.queue.append(self.window.queue[0])
        self.window.queue_changed()
        self.window.crossfade.setValue(.5)
        self.window.start_queue()
        self.wait_for(lambda: self.window.index == 1)
        self.assertFalse(self.window.seek.isEnabled())
        self.window.skip()
        self.wait_for(lambda: self.window.deck.state == 'playing' and self.window.index == 2)
        self.window.stop_queue()
        actions = [e['action'] for e in self.window.store.events()]
        self.assertEqual(actions.count('skipped'), 1)
        self.assertEqual(actions.count('completed'), 0)
        self.assertEqual(actions.count('started'), 3)
        self.assertEqual(actions.count('tail_interrupted'), 1)

    def test_missed_output_deadline_is_reported_instead_of_silent_resume(self):
        self.import_and_queue()
        self.choose_output()
        self.window.start_queue()
        self.wait_for(lambda: self.window.deck.state == 'playing')
        # Deliberately starve the real Windows sink, without pumping GUI events.
        time.sleep(.7)
        self.wait_for(lambda: not self.window.running)
        self.assertEqual(self.window.deck.state, 'error')
        self.assertIn('Подача звука задержалась', self.window.notice.text())
        self.assertEqual(sum(e['action'] == 'completed' for e in self.window.store.events()), 0)

    def test_cancelling_stop_after_current_keeps_transition(self):
        self.import_and_queue()
        self.choose_output()
        self.window.crossfade.setValue(.5)
        self.window.stop_after.setChecked(True)
        self.window.start_queue()
        self.wait_for(lambda: self.window.deck.state == 'playing')
        self.window.stop_after.setChecked(False)
        self.wait_for(lambda: not self.window.running, 12000)
        actions = [e['action'] for e in self.window.store.events()]
        self.assertEqual(actions.count('started'), 2)
        self.assertEqual(actions.count('completed'), 2)
        self.assertEqual(actions.count('transition'), 1)


if __name__ == '__main__':
    unittest.main()
