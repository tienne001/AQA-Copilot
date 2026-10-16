import threading
import time
import unittest
import json
import os
from pathlib import Path
import wave

import numpy as np
from copilot.audio import (AudioSession, LatestQueue, SpeechEngine, StreamingSegmenter,
                           SileroStreamingVad, to_mono_16k)


class AudioTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('AQA_RUN_ASR_ACCURACY') == '1', 'Explicit real GPU accuracy probe')
    def test_real_medium_preserves_aqa_technical_terms(self):
        from copilot.bootstrap import configure_runtime
        configure_runtime()
        fixture_dir = Path(__file__).resolve().parents[2] / 'testing/fixtures'
        expected = json.loads((fixture_dir / 'questions.json').read_text(encoding='utf-8-sig'))
        required = [('регрессионное', 'тестирование'), ('HTTP', 'PUT', 'PATCH'),
                    ('индекс', 'SQL'), ('consumer group', 'offset', 'Kafka'), ('API', 'Playwright')]
        engine = SpeechEngine(os.environ.get('AQA_ASR_TEST_MODEL', 'D:/AQA-Copilot-Data/models/whisper-medium'))
        print('ASR_LOAD ' + json.dumps(engine.load()), flush=True)
        results = []
        for case, question in enumerate(expected, 1):
            with wave.open(str(fixture_dir / f'question-{case}.wav'), 'rb') as wav:
                samples = np.frombuffer(wav.readframes(wav.getnframes()), np.int16).astype(np.float32) / 32768.
                samples = samples.reshape(-1, wav.getnchannels())
                samples = to_mono_16k(samples, wav.getframerate())
            result = engine.transcribe(samples)
            results.append(result)
            print('ASR_PROBE ' + json.dumps({'case': case, 'expected': question, **result}, ensure_ascii=False), flush=True)
        for case, (result, terms) in enumerate(zip(results, required), 1):
            with self.subTest(case=case):
                for term in terms:
                    self.assertIn(term.lower(), result['text'].lower())

    def test_stereo_48k_becomes_mono_16k(self):
        values = np.column_stack([np.ones(4800), np.zeros(4800)])
        result = to_mono_16k(values, 48000)
        self.assertEqual(result.shape, (1600,))
        self.assertAlmostEqual(float(result[100]), .5, places=3)

    def test_silence_and_short_noise_never_emit(self):
        vad = StreamingSegmenter(pause_ms=480)
        for i in range(100):
            self.assertIsNone(vad.feed(np.zeros(512, np.float32), 0., i * .032))
        self.assertIsNone(vad.feed(np.ones(512, np.float32), .9, 4.))
        emitted = [vad.feed(np.zeros(512, np.float32), 0., 4.032 + i*.032) for i in range(20)]
        self.assertTrue(all(item is None for item in emitted))

    def test_endpoint_480ms_after_last_voiced_frame(self):
        vad = StreamingSegmenter(pause_ms=480)
        for i in range(12):
            self.assertIsNone(vad.feed(np.ones(512, np.float32)*.1, .9, 10+i*.032))
        for i in range(14):
            self.assertIsNone(vad.feed(np.zeros(512, np.float32), 0., 10.384+i*.032))
        result = vad.feed(np.zeros(512, np.float32), 0., 10.832)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['speech_end_at'], 10.384, places=3)
        self.assertAlmostEqual(result['endpoint_ms'], 480., places=2)
        self.assertGreater(len(result['samples']), 12*512)

    def test_backpressure_keeps_only_latest_two_segments(self):
        queue = LatestQueue(2)
        for number in range(10):
            queue.put(number)
        self.assertEqual(queue.dropped, 8)
        self.assertEqual([queue.get(.01), queue.get(.01)], [8, 9])

    def test_real_silero_has_independent_stream_states_and_detects_silence(self):
        first, second = SileroStreamingVad(), SileroStreamingVad()
        self.assertLess(first(np.zeros(512, np.float32)), .1)
        self.assertLess(second(np.zeros(512, np.float32)), .1)
        self.assertIsNot(first.h, second.h)
        with self.assertRaises(ValueError):
            first(np.zeros(100, np.float32))

    def test_missing_local_model_fails_without_network_download(self):
        with self.assertRaises(FileNotFoundError):
            SpeechEngine('this-model-does-not-exist').load()

    def test_stop_discards_inflight_transcription(self):
        entered, release = threading.Event(), threading.Event()
        class Engine:
            pause_ms = 480
            def transcribe(self, samples):
                entered.set()
                release.wait(2)
                return {'text': 'do not deliver', 'asr_ms': 1.}
        delivered = []
        session = AudioSession(Engine(), 'microphone', 0, lambda e: None, delivered.append)
        session._stop.clear()
        session._generation = 1
        session._segments.put({'samples': np.ones(6000), 'captured_at': time.monotonic(),
                              'speech_end_at': time.monotonic(), 'endpoint_ms': 480.})
        worker = threading.Thread(target=session._recognize, args=(1,))
        worker.start()
        self.assertTrue(entered.wait(1))
        session.stop()
        release.set()
        worker.join(2)
        self.assertEqual(delivered, [])

    def test_transcript_reports_source_timings_without_retaining_samples(self):
        class Engine:
            pause_ms = 480
            def transcribe(self, samples):
                return {'text': 'Проверка API', 'asr_ms': 12.}
        delivered = []
        session = AudioSession(Engine(), 'loopback', 0, lambda e: None, lambda e: (delivered.append(e), session.stop()))
        session._stop.clear()
        session._generation = 1
        now = time.monotonic()
        session._segments.put({'samples': np.ones(6000), 'captured_at': now,
                               'speech_end_at': now-.48, 'endpoint_ms': 480.})
        session._recognize(1)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['source'], 'loopback')
        self.assertEqual(delivered[0]['text'], 'Проверка API')
        self.assertEqual(delivered[0]['endpoint_ms'], 480.)
        self.assertNotIn('samples', delivered[0])

    def test_cancel_during_model_load_does_not_start_native_decode(self):
        cancelled = threading.Event()
        class Model:
            def transcribe(self, *args, **kwargs):
                raise AssertionError('Native decode must not start after cancellation')
        class Engine(SpeechEngine):
            def load(self):
                self.model = Model()
                cancelled.set()
        result = Engine('unused').transcribe(np.ones(6000, np.float32)*.1, cancelled=cancelled.is_set)
        self.assertEqual(result['text'], '')


if __name__ == '__main__':
    unittest.main()
