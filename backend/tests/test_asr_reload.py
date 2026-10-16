import gc
import threading
import time
import weakref

import numpy as np
import pytest
from fastapi.testclient import TestClient

from copilot.audio import AudioSession, SpeechEngine
from copilot.service import create_app

HEADERS = {'Authorization': 'Bearer test-secret'}


class IdleModel:
    pass


def test_retired_engine_cannot_allocate_again_for_a_queued_warmup():
    engine = SpeechEngine('unused')
    engine.model = IdleModel()
    assert engine.unload(.01)
    with pytest.raises(RuntimeError, match='ASR'):
        engine.transcribe(np.ones(6000, np.float32)*.1)


def test_stopped_session_cannot_resurrect_when_start_was_queued(tmp_path):
    session = AudioSession(SpeechEngine('unused'), 'loopback', 0, lambda e: None, lambda e: None)
    session._capture = lambda generation: None
    session.stop()
    try:
        with pytest.raises(RuntimeError):
            session.start()
        assert not session.active
    finally:
        session.stop()


def test_stop_removes_session_and_asr_reload_releases_old_model(tmp_path):
    app = create_app(tmp_path, 'test-secret', startup_warmup=False)
    runtime = app.state.runtime
    engine = SpeechEngine('unused')
    engine.model = IdleModel()
    model_ref, engine_ref = weakref.ref(engine.model), weakref.ref(engine)
    session = AudioSession(engine, 'loopback', 0, lambda e: None, lambda e: None)
    session_ref = weakref.ref(session)
    runtime.engine, runtime.audio['loopback'] = engine, session
    del engine, session
    with TestClient(app) as client:
        assert client.post('/audio/stop', json={'source': 'loopback'}, headers=HEADERS).status_code == 200
        assert runtime.audio == {}, 'Stopped sessions must leave the active registry'
        gc.collect()
        assert session_ref() is None
        assert client.put('/settings', json={'pause_ms': 640}, headers=HEADERS).status_code == 200
        gc.collect()
        assert runtime.engine is None
        assert engine_ref() is None and model_ref() is None, 'Old native model must have no lingering session owner'


def test_reload_retries_while_stopped_session_native_decode_is_running(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class BlockingModel:
        def transcribe(self, *args, **kwargs):
            entered.set()
            release.wait(5)
            return iter(()), None
    app = create_app(tmp_path, 'test-secret', startup_warmup=False)
    runtime = app.state.runtime
    engine = SpeechEngine('unused')
    engine.model = BlockingModel()
    native_ref = weakref.ref(engine.model)
    runtime.engine = engine
    session = AudioSession(engine, 'microphone', 0, lambda e: None, lambda e: None)
    session._stop.clear()
    session._generation = 1
    session._segments.put({'samples': np.ones(6000, np.float32)*.1, 'captured_at': time.monotonic(),
                           'speech_end_at': time.monotonic(), 'endpoint_ms': 480.})
    session._worker_thread = threading.Thread(target=session._recognize, args=(1,), daemon=True)
    runtime.audio['microphone'] = session
    session._worker_thread.start()
    assert entered.wait(1)
    try:
        with TestClient(app) as client:
            started = time.monotonic()
            assert client.post('/audio/stop', json={}, headers=HEADERS).status_code == 200
            assert time.monotonic()-started < .8, 'Ordinary stop must not await native inference completion'
            assert runtime.audio == {}
            response = client.put('/settings', json={'pause_ms': 640}, headers=HEADERS)
            assert response.status_code == 409, response.text
            assert runtime.engine is engine and engine.model is native_ref()
            assert runtime.settings.pause_ms == 480, 'Rejected reload must leave settings unchanged'
            release.set()
            assert session.drain(1)
            assert client.put('/settings', json={'pause_ms': 640}, headers=HEADERS).status_code == 200
            assert runtime.engine is None and engine.model is None
            gc.collect()
            assert native_ref() is None
    finally:
        release.set()
        session._worker_thread.join(2)


def test_reload_waits_for_direct_engine_decode_without_an_audio_session(tmp_path):
    app = create_app(tmp_path, 'test-secret', startup_warmup=False)
    runtime = app.state.runtime
    engine = SpeechEngine('unused')
    engine.model = IdleModel()
    runtime.engine = engine
    entered, release = threading.Event(), threading.Event()
    def native_operation():
        with engine._lock:
            entered.set()
            release.wait(5)
    worker = threading.Thread(target=native_operation, daemon=True)
    worker.start()
    assert entered.wait(1)
    try:
        with TestClient(app) as client:
            response = client.put('/settings', json={'pause_ms': 640}, headers=HEADERS)
            assert response.status_code == 409, response.text
            assert runtime.engine is engine and engine.model is not None
            release.set()
            worker.join(1)
            assert client.put('/settings', json={'pause_ms': 640}, headers=HEADERS).status_code == 200
            assert runtime.engine is None and engine.model is None
    finally:
        release.set()
        worker.join(2)
