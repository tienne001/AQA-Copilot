"""Warmup must prepare the same Ollama runner shape as normal answers."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.mark.parametrize('model,seed', [('qwen3:8b',None), ('qwen3:8b',42), ('gemma4:12b-it-qat',42), ('gemma4:12b-it-qat',None)])
def test_warmup_and_actual_chat_use_same_runner_resource_options(tmp_path, monkeypatch, model, seed):
    from copilot import service
    from copilot.model_spec import MODEL_CATALOG
    from copilot.settings import Settings

    monkeypatch.setattr(service, 'configure_runtime', lambda: None)
    runtime = service.Runtime(tmp_path)
    runtime.settings = Settings(model=model, seed=seed, num_ctx=4096, history_enabled=False, knowledge_enabled=False)
    runtime.asr = {'loaded': True, 'device': 'mock'}
    monkeypatch.setattr(runtime, 'load_engine', AsyncMock(return_value=object()))
    ensure = AsyncMock()
    monkeypatch.setattr(runtime.ollama, 'ensure', ensure)
    decoder_calls = []

    async def fake_to_thread(function, *args, **kwargs):
        # Do not load ASR, decode audio or allocate GPU memory in this HTTP test.
        decoder_calls.append(function.__name__)
        return {'text': 'mock warmup', 'asr_ms': 1.0}

    monkeypatch.setattr(service.asyncio, 'to_thread', fake_to_thread)
    chat_requests = []

    def request(request):
        assert request.url.host == '127.0.0.1'
        if request.url.path == '/api/tags':
            digest, minimum_size = MODEL_CATALOG.get(runtime.settings.model, ('a'*64, 1000))
            return httpx.Response(200, json={'models': [{
                'name': runtime.settings.model, 'digest': digest, 'size': minimum_size,
                'details': {'format': 'gguf', 'family': 'qwen3'},
            }]})
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities':['completion']})
        assert request.method == 'POST' and request.url.path == '/api/chat'
        body = json.loads(request.content)
        chat_requests.append(body)
        if not body['stream']:
            return httpx.Response(200, json={'done': True, 'message': {'content': 'готово'}})
        chunks = [
            {'message': {'content': 'Готовый ответ для проверки.'}, 'done': False},
            {'done': True, 'eval_count': 4, 'eval_duration': 1000000},
        ]
        return httpx.Response(200, content=''.join(json.dumps(chunk) + '\n' for chunk in chunks),
                              headers={'Content-Type': 'application/x-ndjson'})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, 'AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(request), **kwargs))

    async def scenario():
        warmed = await runtime.warmup()
        assert warmed['errors'] == []
        assert warmed['ready'] is True
        events = [event async for event in runtime.chat.stream('Проверь готовность модели')]
        assert events[-1]['type'] == 'done'

    try:
        asyncio.run(scenario())
        assert decoder_calls == ['warm_decode']
        ensure.assert_awaited_once_with(runtime.settings.ollama_url)
        assert len(chat_requests) == 2
        warmup, answer = chat_requests
        assert warmup['stream'] is False and answer['stream'] is True
        for parameter in ('num_ctx', 'num_batch', 'num_thread'):
            assert warmup['options'][parameter] == answer['options'][parameter], parameter
        assert warmup['options']['num_thread'] == 4
        assert warmup['think'] is False
        assert warmup['options']['num_predict'] == 8
        assert warmup['options']['temperature'] == 0
        assert warmup['options'].get('seed') == answer['options'].get('seed') == seed
        if seed is None:
            assert 'seed' not in warmup['options'] and 'seed' not in answer['options']
        expected_prompt = 'Ответь одним словом: готово.' + (' /no_think' if model.startswith('qwen') else '')
        assert warmup['messages'] == [{'role':'user', 'content':expected_prompt}]
        if model.startswith('gemma'):
            assert answer['messages'][-1]['content'] == 'Проверь готовность модели'
        else:
            assert answer['messages'][-1]['content'].endswith('\n/no_think')
    finally:
        runtime.store.close()
