"""Authenticated loopback API. Capture and inference require explicit local actions."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
from pathlib import Path
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from . import __version__
from .bootstrap import configure_runtime
from .llm import ChatManager, sse
from .model_adapter import system_instruction
from .ollama_runtime import OllamaRuntime, verify_local_model
from .settings import Settings, load_settings, save_settings
from .storage import Store
from .telemetry import GpuMonitor

ORIGINS = {'http://tauri.localhost', 'https://tauri.localhost', 'tauri://localhost',
           'http://localhost:1420', 'http://127.0.0.1:1420'}


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=6000)
    session_id: str | None = None
    ocr_context: str = Field(default='', max_length=30000)

class AudioBody(BaseModel):
    source: str
    device_index: int = Field(ge=0)

class StopBody(BaseModel):
    source: str | None = None

class CaptureBody(BaseModel):
    window_id: int = Field(gt=0)

class ImportBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200000)
    as_profile: bool = False


class Runtime:
    def __init__(self, data_dir):
        configure_runtime()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = load_settings(self.data_dir)
        self.store = Store(self.data_dir / 'copilot.db')
        self.store.seed_knowledge(Path(__file__).resolve().parents[1] / 'knowledge')
        self.chat = ChatManager(self.store, lambda: self.settings)
        self.ollama = OllamaRuntime(self.data_dir)
        self.gpu = GpuMonitor()
        self.engine = None
        self.asr = {'loaded': False, 'device': self.settings.asr_device}
        self.audio = {}
        self._draining_audio = []
        self.generations = {'loopback': 0, 'microphone': 0}
        self.subscribers = set()
        self.warm_lock = asyncio.Lock()
        self.warming_up = False
        self.warmup_errors = []
        self.active_session = None
        self.auto_tasks = set()
        self.loop = None

    def publish(self, event):
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def load_engine(self):
        async with self.warm_lock:
            if self.engine is None:
                if self.settings.asr_device == 'cuda':
                    # Reserve room for weights and decoder buffers before allocating.
                    # Large-v3 needs a larger budget than medium; estimates are
                    # conservative guards, not guarantees against other GPU apps.
                    weights = Path(self.settings.asr_model_path) / 'model.bin'
                    weight_mb = weights.stat().st_size // (1024 * 1024) if weights.is_file() else 0
                    asr_budget = max(2000, weight_mb + 1500)
                    if self.settings.asr_compute_type in ('float32', 'float16'):
                        asr_budget = max(asr_budget, weight_mb * 2 + 1500)
                    await self.gpu.require_free(self.settings.vram_reserve_mb + asr_budget)
                from .audio import SpeechEngine
                engine = SpeechEngine(self.settings.asr_model_path, self.settings.asr_device,
                                      self.settings.asr_compute_type, self.settings.pause_ms)
                self.asr = await asyncio.to_thread(engine.load)
                self.engine = engine
            return self.engine

    async def warmup(self):
        self.warming_up = True
        started = time.perf_counter()
        errors = []
        try:
            engine = await self.load_engine()
            def warm_decode():
                # A bundled synthetic question warms real CUDA decoder kernels,
                # not merely model weight allocation. No microphone is opened.
                import av
                from .audio import to_mono_16k
                import numpy as np
                fixture = Path(__file__).resolve().parents[1] / 'fixtures/warmup.wav'
                with av.open(str(fixture)) as container:
                    stream = container.streams.audio[0]
                    chunks = [frame.to_ndarray() for frame in container.decode(stream)]
                    samples = np.concatenate(chunks, axis=1).astype(np.float32)
                    if samples.max(initial=0) > 1:
                        samples /= 32768.
                    return engine.transcribe(to_mono_16k(samples.T, stream.rate))
            decoded = await asyncio.to_thread(warm_decode)
            self.asr['warm_decode_ms'] = decoded['asr_ms']
        except Exception as error:
            self.asr = {'loaded': False, 'device': self.settings.asr_device, 'error': str(error)}
            errors.append('ASR: ' + str(error))
        try:
            await self.ollama.ensure(self.settings.ollama_url)
            async with httpx.AsyncClient(trust_env=False, timeout=120) as client:
                await verify_local_model(client, self.settings.ollama_url, self.settings.model)
                body = {
                    'model': self.settings.model, 'messages': [{'role': 'user', 'content':
                        system_instruction('Ответь одним словом: готово. /no_think', self.settings.model, False)}],
                    'think': False, 'stream': False, 'keep_alive': '30m',
                    'options': {'num_ctx': self.settings.num_ctx, 'num_predict': 8, 'temperature': 0,
                                'num_batch': 256, 'num_thread': 4}}
                if self.settings.seed is not None:
                    body['options']['seed'] = self.settings.seed
                response = await client.post(self.settings.ollama_url + '/api/chat', json=body)
                response.raise_for_status()
                result = response.json()
                if result.get('error'):
                    raise RuntimeError(result['error'])
        except Exception as error:
            errors.append('Ollama: ' + str(error))
        event = {'type': 'status', 'ready': not errors, 'asr': self.asr,
                 'warmup_ms': (time.perf_counter()-started)*1000, 'errors': errors}
        self.warming_up = False
        self.warmup_errors = errors
        self.publish(event)
        return event

    async def auto_answer(self, segment, generation):
        source = segment['source']
        if self.generations[source] != generation:
            return
        self.publish({'type': 'transcript', **segment})
        should_answer = self.settings.auto_answer if source == 'loopback' else self.settings.microphone_auto_answer
        if not should_answer:
            return
        metrics = {key: segment[key] for key in ('asr_ms', 'endpoint_ms', 'speech_end_at') if key in segment}
        if self.active_session is None:
            self.active_session = self.store.new_session()
        try:
            if self.settings.asr_device == 'cuda':
                await self.gpu.require_free(self.settings.vram_reserve_mb)
            if self.generations[source] != generation:
                return
            async for event in self.chat.stream(segment['text'], self.active_session, speech_metrics=metrics):
                if self.generations[source] != generation:
                    break
                self.publish(event)
        except Exception as error:
            self.publish({'type': 'error', 'error': str(error)})

    def deliver_segment(self, segment, generation):
        task = asyncio.create_task(self.auto_answer(segment, generation))
        self.auto_tasks.add(task)
        task.add_done_callback(self.auto_tasks.discard)

    async def stop_audio(self, source=None):
        targets = [source] if source else ['loopback', 'microphone']
        if any(item not in self.generations for item in targets):
            raise ValueError('Источник: loopback или microphone')
        for item in targets:
            self.generations[item] += 1
            session = self.audio.pop(item, None)
            if session is not None:
                # Invalidate synchronously, including a start queued in the thread pool.
                # Ordinary stop never waits for a native ASR operation to finish.
                session.stop(capture_timeout=0)
                self._draining_audio.append(session)
        self._draining_audio = [session for session in self._draining_audio if not session.drain(0)]
        await self.chat.cancel()


def create_app(data_dir, token, startup_warmup=False):
    runtime = Runtime(data_dir)
    @asynccontextmanager
    async def lifespan(app):
        runtime.loop = asyncio.get_running_loop()
        task = asyncio.create_task(runtime.warmup()) if startup_warmup else None
        yield
        await runtime.stop_audio()
        for auto_task in tuple(runtime.auto_tasks):
            auto_task.cancel()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        runtime.store.close()
        runtime.ollama.close()
    app = FastAPI(title='AQA Copilot Local', version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    app.add_middleware(CORSMiddleware, allow_origins=list(ORIGINS), allow_methods=['GET','POST','PUT','DELETE'],
                       allow_headers=['Authorization','Content-Type'])

    @app.middleware('http')
    async def local_auth(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in ORIGINS:
            return JSONResponse({'detail': 'Внешний Origin запрещён'}, status_code=403)
        if request.method != 'OPTIONS' and not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
            return JSONResponse({'detail': 'Требуется токен локального приложения'}, status_code=401)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({'detail': str(error)}, status_code=400)

    @app.get('/health')
    async def health():
        ollama = {'available': False, 'model': runtime.settings.model}
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                response = await client.get(runtime.settings.ollama_url + '/api/tags')
                response.raise_for_status()
                models = response.json().get('models', [])
                ollama.update(available=True, installed=any(item.get('name') == runtime.settings.model for item in models))
        except Exception as error:
            ollama['error'] = str(error)
        return {'ready': True, 'version': __version__, 'asr': runtime.asr, 'ollama': ollama,
                'warming_up': runtime.warming_up, 'warmup_errors': runtime.warmup_errors}

    @app.get('/settings')
    async def get_settings():
        return runtime.settings

    @app.put('/settings')
    async def put_settings(body: dict):
        try:
            updated = Settings.model_validate({**runtime.settings.model_dump(), **body})
        except ValueError as error:
            raise HTTPException(422, str(error))
        asr_changed = any(getattr(updated, field) != getattr(runtime.settings, field)
                          for field in ('asr_model_path', 'asr_device', 'asr_compute_type', 'pause_ms'))
        if not asr_changed:
            await runtime.chat.cancel()
        async with runtime.warm_lock:
            if asr_changed:
                # Share the allocation lock so no audio start can acquire the retiring
                # engine while its sessions are being stopped and drained.
                await runtime.stop_audio()
                for session in tuple(runtime._draining_audio):
                    if not await asyncio.to_thread(session.drain, .25):
                        raise HTTPException(409, 'ASR ещё завершает аудиопоток или распознавание; повторите изменение настроек через несколько секунд')
                runtime._draining_audio.clear()
                if runtime.engine is not None and not await asyncio.to_thread(runtime.engine.unload, .25):
                    raise HTTPException(409, 'ASR ещё завершает распознавание или прогрев; повторите изменение настроек через несколько секунд')
                runtime.engine = None
                runtime.asr = {'loaded': False, 'device': updated.asr_device}
            runtime.settings = updated
            save_settings(runtime.data_dir, updated)
        return updated

    @app.get('/devices')
    async def devices():
        from .audio import list_devices
        return await asyncio.to_thread(list_devices)

    @app.post('/models/warmup')
    async def warmup():
        return await runtime.warmup()

    @app.post('/audio/start')
    async def audio_start(body: AudioBody):
        if body.source not in runtime.generations:
            raise ValueError('Источник: loopback или microphone')
        await runtime.stop_audio(body.source)
        try:
            engine = await runtime.load_engine()
            from .audio import AudioSession
            generation = runtime.generations[body.source]
            session = AudioSession(engine, body.source, body.device_index,
                lambda event: runtime.loop.call_soon_threadsafe(runtime.publish, event),
                lambda segment: runtime.loop.call_soon_threadsafe(runtime.deliver_segment, segment, generation))
            runtime.audio[body.source] = session
            await asyncio.to_thread(session.start)
            return {'started': session.active, 'source': body.source}
        except Exception as error:
            raise HTTPException(503, str(error))

    @app.post('/audio/stop')
    async def audio_stop(body: StopBody = StopBody()):
        await runtime.stop_audio(body.source)
        return {'stopped': True}

    @app.get('/events')
    async def events(request: Request):
        async def stream():
            queue = asyncio.Queue(maxsize=512)
            runtime.subscribers.add(queue)
            try:
                yield sse({'type': 'connected'})
                while not await request.is_disconnected():
                    try:
                        yield sse(await asyncio.wait_for(queue.get(), 15))
                    except asyncio.TimeoutError:
                        yield ': keepalive\n\n'
            finally:
                runtime.subscribers.discard(queue)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control':'no-store'})

    @app.post('/chat')
    async def chat(body: ChatBody):
        if not body.question.strip():
            raise ValueError('Введите вопрос')
        if body.session_id and not runtime.store.exists(body.session_id):
            raise HTTPException(404, 'Диалог не найден')
        if runtime.settings.asr_device == 'cuda':
            try:
                await runtime.gpu.require_free(runtime.settings.vram_reserve_mb)
            except RuntimeError as error:
                raise HTTPException(503, str(error))
        runtime.active_session = body.session_id or runtime.store.new_session()
        return StreamingResponse((sse(event) async for event in runtime.chat.stream(
            body.question.strip(), runtime.active_session, body.ocr_context)), media_type='text/event-stream',
            headers={'Cache-Control':'no-store'})

    @app.post('/cancel')
    async def cancel():
        await runtime.chat.cancel()
        return {'cancelled': True}

    @app.get('/sessions')
    async def sessions():
        return runtime.store.sessions()

    @app.post('/sessions')
    async def new_session():
        await runtime.chat.cancel()
        runtime.active_session = runtime.store.new_session()
        return {'id': runtime.active_session}

    @app.get('/history')
    async def history(session_id: str):
        if not runtime.store.exists(session_id):
            raise HTTPException(404, 'Диалог не найден')
        runtime.active_session = session_id
        return runtime.store.history(session_id)

    @app.delete('/history')
    async def clear_history(session_id: str):
        await runtime.chat.cancel()
        runtime.store.clear_history(session_id)
        return {'cleared': True}

    @app.get('/knowledge/search')
    async def search(q: str):
        return runtime.store.search(q, 8)

    @app.post('/knowledge/import')
    async def import_knowledge(body: ImportBody):
        if body.as_profile and len(body.text) > 6000:
            raise HTTPException(422, 'Профиль опыта должен быть не длиннее 6000 символов')
        runtime.store.import_knowledge(body.title, body.text,
            'user/profile.md' if body.as_profile else 'user/' + str(uuid.uuid4()) + '.md')
        return {'imported': True}

    @app.get('/windows')
    async def windows():
        from .screen import list_windows
        return await asyncio.to_thread(list_windows)

    @app.post('/screen/capture')
    async def capture(body: CaptureBody):
        from .screen import capture_window
        try:
            return await asyncio.to_thread(capture_window, body.window_id, runtime.settings.tesseract_path or None)
        except Exception as error:
            raise HTTPException(422, str(error))

    @app.get('/metrics')
    async def metrics():
        loaded = []
        error = None
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                response = await client.get(runtime.settings.ollama_url + '/api/ps')
                response.raise_for_status()
                loaded = response.json().get('models', [])
        except Exception as failure:
            error = str(failure)
        return {'gpu': await runtime.gpu.read(), 'ollama_models': loaded, 'ollama_error': error,
                'latest': runtime.chat.latest, 'asr': runtime.asr,
                'audio': {source: source in runtime.audio and runtime.audio[source].active for source in runtime.generations},
                'queue_dropped': sum(item.queue_dropped for item in runtime.audio.values())}
    return app
