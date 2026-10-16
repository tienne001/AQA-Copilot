from fastapi.testclient import TestClient


def test_local_api_requires_token_and_rejects_foreign_origins(tmp_path):
    from copilot.service import create_app
    with TestClient(create_app(tmp_path, 'test-secret', startup_warmup=False)) as client:
        assert client.get('/settings').status_code == 401
        assert client.get('/settings', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        headers = {'Authorization': 'Bearer test-secret'}
        assert client.get('/settings', headers={**headers, 'Origin': 'https://evil.test'}).status_code == 403
        assert client.get('/settings', headers={**headers, 'Origin': 'http://tauri.localhost'}).status_code == 200
        assert client.put('/settings', json={'ollama_url': 'https://cloud.test'}, headers=headers).status_code == 422


def test_session_history_and_russian_knowledge_are_real(tmp_path):
    from copilot.service import create_app
    with TestClient(create_app(tmp_path, 'test-secret', startup_warmup=False)) as client:
        headers = {'Authorization': 'Bearer test-secret'}
        session = client.post('/sessions', headers=headers).json()['id']
        assert client.get('/history', params={'session_id': session}, headers=headers).json() == []
        imported = client.post('/knowledge/import', headers=headers, json={'title': 'Тест Kafka', 'text': 'Kafka consumer offset смещение партиции'})
        assert imported.status_code == 200
        hits = client.get('/knowledge/search', params={'q': 'Kafka'}, headers=headers).json()
        assert any(item['title'] == 'Тест Kafka' for item in hits)
        assert client.get('/sessions', headers=headers).json()[0]['id'] == session


def test_llm_only_settings_keep_the_loaded_asr_engine(tmp_path):
    from copilot.service import create_app
    app = create_app(tmp_path, 'test-secret', startup_warmup=False)
    loaded = object()
    app.state.runtime.engine = loaded
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer test-secret'}
        assert client.put('/settings', json={'num_predict': 160}, headers=headers).status_code == 200
        assert app.state.runtime.engine is loaded, 'LLM options must not unload/reallocate ASR VRAM'


def test_low_vram_rejects_new_inference_before_http_stream_is_started(tmp_path):
    import time
    from copilot.service import create_app
    app = create_app(tmp_path, 'test-secret', startup_warmup=False)
    app.state.runtime.gpu.value = {'available': True, 'free_mb': 100, 'used_mb': 16000, 'total_mb':16376}
    app.state.runtime.gpu.updated = time.monotonic()
    with TestClient(app) as client:
        response = client.post('/chat', json={'question':'Объясни SQL'}, headers={'Authorization':'Bearer test-secret'})
        assert response.status_code == 503
        assert 'VRAM' in response.json()['detail']


def test_stopped_audio_waiter_cannot_supersede_newer_manual_chat(tmp_path):
    import asyncio
    from copilot.service import Runtime
    async def scenario():
        runtime = Runtime(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def delayed_gpu_check(_):
            entered.set()
            await release.wait()
        class Chat:
            async def cancel(self):
                pass
            async def stream(self, question, *args, **kwargs):
                calls.append(question)
                yield {'type':'done'}
        runtime.gpu.require_free = delayed_gpu_check
        runtime.chat = Chat()
        stale = asyncio.create_task(runtime.auto_answer({'source':'loopback','text':'старый голос'}, 0))
        await entered.wait()
        await runtime.stop_audio('loopback')
        async for _ in runtime.chat.stream('новый ручной вопрос'):
            pass
        release.set()
        await stale
        assert calls == ['новый ручной вопрос']
        runtime.store.close()
    asyncio.run(scenario())


def test_explicit_profile_import_replaces_pinned_facts_and_limits_size(tmp_path):
    from copilot.service import create_app
    app = create_app(tmp_path, 'test-secret', startup_warmup=False)
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer test-secret'}
        for text in ('Playwright', 'Playwright + TypeScript'):
            response = client.post('/knowledge/import', headers=headers,
                json={'title': 'Resume', 'text': text, 'as_profile': True})
            assert response.status_code == 200
        assert app.state.runtime.store.profile()['text'] == 'Playwright + TypeScript'
        assert client.post('/knowledge/import', headers=headers,
            json={'title': 'Too long', 'text': 'x' * 6001, 'as_profile': True}).status_code == 422
        assert app.state.runtime.store.profile()['text'] == 'Playwright + TypeScript'
        assert client.post('/knowledge/import', headers=headers,
            json={'title': 'Reference', 'text': 'Ordinary technical material'}).status_code == 200
        assert app.state.runtime.store.profile()['title'] == 'Resume'


def test_large_asr_checks_vram_budget_before_allocating(tmp_path):
    import asyncio
    from copilot.service import Runtime
    runtime = Runtime(tmp_path / 'data')
    model = tmp_path / 'model'
    model.mkdir()
    # Sparse file: tests metadata-based guard without allocating model RAM.
    with (model / 'model.bin').open('wb') as stream:
        stream.truncate(3000 * 1024 * 1024)
    runtime.settings.asr_model_path = str(model)
    runtime.settings.vram_reserve_mb = 2048
    budgets = []
    async def deny(minimum):
        budgets.append(minimum)
        raise RuntimeError('budget guard')
    runtime.gpu.require_free = deny
    import pytest
    with pytest.raises(RuntimeError, match='budget guard'):
        asyncio.run(runtime.load_engine())
    assert budgets == [6548]
    assert runtime.engine is None
    runtime.store.close()
