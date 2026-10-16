"""Local-only speech capture. Audio stays in bounded memory and is never written to disk."""
from collections import deque
from math import gcd
from pathlib import Path
import queue
import threading
import time

import numpy as np
from scipy.signal import resample_poly
from .speech_vocabulary import AQA_HOTWORDS, normalize_technical_terms

RATE = 16000
FRAME = 512


def to_mono_16k(samples: np.ndarray, source_rate: int) -> np.ndarray:
    if source_rate <= 0:
        raise ValueError('Некорректная частота аудио')
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1:
        raise ValueError('Ожидается mono/stereo массив аудио')
    if source_rate != RATE:
        divisor = gcd(int(source_rate), RATE)
        samples = resample_poly(samples, RATE // divisor, int(source_rate) // divisor)
    return np.ascontiguousarray(samples, dtype=np.float32)


class LatestQueue:
    """A small queue which replaces the oldest pending utterance under load."""
    def __init__(self, capacity=2):
        self._queue = queue.Queue(maxsize=capacity)
        self.dropped = 0
        self._lock = threading.Lock()

    def put(self, item):
        with self._lock:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass
            self._queue.put_nowait(item)

    def get(self, timeout=.1):
        return self._queue.get(timeout=timeout)

    def clear(self):
        with self._lock:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    return


class SileroStreamingVad:
    """faster-whisper's bundled Silero v6 ONNX; recurrent state belongs to this stream."""
    def __init__(self):
        from faster_whisper.vad import get_vad_model
        self.session = get_vad_model().session
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros_like(self.h)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def __call__(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.shape != (FRAME,):
            raise ValueError('Silero VAD требует ровно 512 mono samples / 16 kHz')
        model_input = np.concatenate((self.context, samples.reshape(1, FRAME)), axis=1)
        output, self.h, self.c = self.session.run(None, {'input': model_input, 'h': self.h, 'c': self.c})
        self.context = samples[-64:].reshape(1, 64).copy()
        return float(np.asarray(output).reshape(-1)[0])


class StreamingSegmenter:
    def __init__(self, pause_ms=480, min_speech_ms=256, max_seconds=15):
        if not 160 <= pause_ms <= 5000:
            raise ValueError('Пауза должна быть 160–5000 мс')
        self.pause = int(RATE * pause_ms / 1000)
        self.minimum = int(RATE * min_speech_ms / 1000)
        self.maximum = int(RATE * max_seconds)
        self.preroll = deque(maxlen=5)
        self.parts = []
        self.voiced = self.quiet = self.length = 0
        self.speech_end_at = 0.

    def feed(self, frame, probability, captured_at):
        speech = probability >= (.35 if self.parts else .5)
        if not self.parts:
            if not speech:
                self.preroll.append(frame.copy())
                return None
            self.parts = list(self.preroll)
            self.length = sum(map(len, self.parts))
            self.preroll.clear()
        self.parts.append(frame.copy())
        self.length += len(frame)
        if speech:
            self.voiced += len(frame)
            self.quiet = 0
            self.speech_end_at = captured_at + len(frame) / RATE
        else:
            self.quiet += len(frame)
        if self.quiet < self.pause and self.length < self.maximum:
            return None
        result = None
        if self.voiced >= self.minimum:
            result = {'samples': np.concatenate(self.parts), 'captured_at': captured_at + len(frame)/RATE,
                      'speech_end_at': self.speech_end_at,
                      'endpoint_ms': max(0., (captured_at+len(frame)/RATE-self.speech_end_at)*1000)}
        self.parts = []
        self.voiced = self.quiet = self.length = 0
        return result


class SpeechEngine:
    def __init__(self, model_path: str, device='cuda', compute_type='int8_float16', pause_ms=480):
        self.model_path = str(model_path)
        self.device = device
        self.compute_type = compute_type
        self.pause_ms = pause_ms
        self.model = None
        self._closed = False
        self._lock = threading.RLock()
        self.load_ms = 0.

    def load(self):
        with self._lock:
            if self._closed:
                raise RuntimeError('Движок ASR выгружен; повторите запрос с новым движком')
            if self.model is None:
                if not (Path(self.model_path) / 'model.bin').is_file():
                    raise FileNotFoundError('Локальная faster-whisper модель не найдена: ' + self.model_path)
                from faster_whisper import WhisperModel
                started = time.perf_counter()
                self.model = WhisperModel(self.model_path, device=self.device, compute_type=self.compute_type,
                                          cpu_threads=4, num_workers=1, local_files_only=True)
                SileroStreamingVad()
                self.load_ms = (time.perf_counter()-started)*1000
            return {'loaded': True, 'device': self.device, 'compute_type': self.compute_type,
                    'load_ms': self.load_ms, 'vad': 'silero_v6_onnx', 'sample_rate': RATE}

    def unload(self, timeout=0):
        """Retire this engine only once native decoding has released its lock."""
        if not self._lock.acquire(timeout=max(0., timeout)):
            return False
        try:
            self._closed = True
            self.model = None
            return True
        finally:
            self._lock.release()

    def transcribe(self, samples, cancelled=None):
        started = time.perf_counter()
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not np.all(np.isfinite(samples)):
            raise ValueError('Нужен конечный mono float32 массив / 16 kHz')
        if samples.size < 4096 or np.max(np.abs(samples), initial=0.) < .002:
            return {'text': '', 'asr_ms': (time.perf_counter()-started)*1000}
        with self._lock:
            if cancelled and cancelled():
                return {'text': '', 'asr_ms': 0.}
            self.load()
            if cancelled and cancelled():
                return {'text': '', 'asr_ms': (time.perf_counter()-started)*1000}
            segments, _ = self.model.transcribe(samples, language='ru', beam_size=3, temperature=0,
                hotwords=AQA_HOTWORDS,
                condition_on_previous_text=False, vad_filter=True,
                vad_parameters={'min_speech_duration_ms': 128, 'min_silence_duration_ms': self.pause_ms},
                no_speech_threshold=.6, hallucination_silence_threshold=1.)
            text = []
            for segment in segments:
                if cancelled and cancelled():
                    break
                if segment.no_speech_prob < .6 and segment.text.strip():
                    text.append(segment.text.strip())
        raw_text = ' '.join(text)
        corrected, corrections = normalize_technical_terms(raw_text)
        return {'text': corrected, 'raw_text': raw_text, 'corrections': corrections,
                'asr_ms': (time.perf_counter()-started)*1000}


def list_devices():
    import pyaudiowpatch as pa
    with pa.PyAudio() as audio:
        loopback, microphone = [], []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get('maxInputChannels', 0)) <= 0:
                continue
            item = {'index': int(info['index']), 'name': info['name'],
                    'rate': int(info['defaultSampleRate']), 'channels': int(info['maxInputChannels'])}
            (loopback if info.get('isLoopbackDevice') else microphone).append(item)
        try:
            default_loopback = int(audio.get_default_wasapi_loopback()['index'])
        except (OSError, LookupError):
            default_loopback = None
        try:
            default_microphone = int(audio.get_default_input_device_info()['index'])
        except (OSError, LookupError):
            default_microphone = None
    return {'loopback': loopback, 'microphone': microphone,
            'default_loopback': default_loopback, 'default_microphone': default_microphone}


class AudioSession:
    def __init__(self, engine, source, device_index, on_event, on_segment):
        if source not in ('loopback', 'microphone'):
            raise ValueError('Неизвестный источник аудио')
        self.engine, self.source, self.device_index = engine, source, int(device_index)
        self.on_event, self.on_segment = on_event, on_segment
        self._segments = LatestQueue(2)
        self._stop = threading.Event()
        self._stop.set()
        self._terminal = False
        self._generation = 0
        self._delivery_lock = threading.RLock()
        self._capture_thread = self._worker_thread = None

    @property
    def active(self):
        return not self._stop.is_set()

    @property
    def queue_dropped(self):
        return self._segments.dropped

    def start(self):
        with self._delivery_lock:
            if self._terminal:
                raise RuntimeError('Аудиосессия остановлена; создайте новую сессию')
            if self.active:
                return
            if self._capture_thread and self._capture_thread.is_alive():
                raise RuntimeError('Предыдущий аудиопоток ещё останавливается')
            self._generation += 1
            generation = self._generation
            self._segments.clear()
            self._stop.clear()
            self._capture_thread = threading.Thread(target=self._capture, args=(generation,), daemon=True)
            self._worker_thread = threading.Thread(target=self._recognize, args=(generation,), daemon=True)
            self._worker_thread.start()
            self._capture_thread.start()

    def stop(self, capture_timeout=.4):
        with self._delivery_lock:
            self._terminal = True
            self._stop.set()
            self._generation += 1
            self._segments.clear()
        # CTranslate2 calls finish their current native operation; their results are discarded.
        if self._capture_thread and self._capture_thread is not threading.current_thread():
            self._capture_thread.join(max(0., capture_timeout))

    def drain(self, timeout=0):
        """Bounded join for a stopped session; False means native work still owns its engine."""
        if self.active:
            return False
        deadline = time.monotonic()+max(0., timeout)
        for thread in (self._capture_thread, self._worker_thread):
            if thread is None:
                continue
            if thread is threading.current_thread():
                return False
            thread.join(max(0., deadline-time.monotonic()))
            if thread.is_alive():
                return False
        return True

    def _valid(self, generation):
        return not self._stop.is_set() and generation == self._generation

    def _emit(self, event, generation):
        with self._delivery_lock:
            if self._valid(generation):
                self.on_event(dict(event, source=self.source))

    def _recognize(self, generation):
        while self._valid(generation):
            try:
                item = self._segments.get(.1)
            except queue.Empty:
                continue
            if not self._valid(generation):
                return
            if time.monotonic() - item['captured_at'] > 20:
                self._segments.dropped += 1
                continue
            try:
                if isinstance(self.engine, SpeechEngine):
                    result = self.engine.transcribe(item['samples'], cancelled=lambda: not self._valid(generation))
                else:
                    result = self.engine.transcribe(item['samples'])
                with self._delivery_lock:
                    if self._valid(generation) and result['text'].strip():
                        self.on_segment({k: v for k, v in dict(item, **result, source=self.source).items()
                                         if k != 'samples'})
            except Exception as error:
                self._emit({'type': 'audio_error', 'error': str(error)}, generation)

    def _capture(self, generation):
        stream = None
        audio = None
        try:
            import pyaudiowpatch as pa
            audio = pa.PyAudio()
            info = audio.get_device_info_by_index(self.device_index)
            if bool(info.get('isLoopbackDevice')) != (self.source == 'loopback'):
                raise ValueError('Устройство не соответствует выбранному источнику')
            rate, channels = int(info['defaultSampleRate']), int(info['maxInputChannels'])
            if channels < 1:
                raise ValueError('Устройство не имеет входных каналов')
            vad, segmenter = SileroStreamingVad(), StreamingSegmenter(self.engine.pause_ms)
            count = int(rate*.064)
            stream = audio.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                                input_device_index=self.device_index, frames_per_buffer=count)
            pending = np.zeros(0, np.float32)
            last_meter = 0.
            while self._valid(generation):
                raw = stream.read(count, exception_on_overflow=True)
                received_at = time.monotonic()
                samples = np.frombuffer(raw, np.int16).reshape(-1, channels).astype(np.float32)/32768.
                pending = np.concatenate((pending, to_mono_16k(samples, rate)))
                if received_at-last_meter >= .08:
                    self._emit({'type': 'audio_level', 'level': float(np.sqrt(np.mean(samples*samples)))}, generation)
                    last_meter = received_at
                while len(pending) >= FRAME and self._valid(generation):
                    frame_time = received_at-len(pending)/RATE
                    frame, pending = pending[:FRAME], pending[FRAME:]
                    item = segmenter.feed(frame, vad(frame), frame_time)
                    if item is not None:
                        self._segments.put(item)
        except Exception as error:
            self._emit({'type': 'audio_error', 'error': str(error)}, generation)
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if audio:
                audio.terminate()
            with self._delivery_lock:
                if self._generation == generation:
                    self._stop.set()
                    self._segments.clear()
