import asyncio
import copy
import pytest
from pydantic import ValidationError
from test_llm import ollama_server
from copilot.model_adapter import system_instruction, user_instruction, uses_native_controls
from copilot.settings import Settings


@pytest.mark.parametrize('value', [True, False, 1.5, '42', -1, 2147483648])
def test_seed_rejects_non_integer_or_out_of_range(value):
    with pytest.raises(ValidationError):
        Settings(seed=value)


@pytest.mark.parametrize('value', [None, 0, 42, 2147483647])
def test_seed_accepts_explicit_integer_or_runtime_default(value):
    assert Settings(seed=value).seed == value


def test_controls_are_scoped_and_preserve_literal_user_data():
    native = 'gemma4:12b-it-qat'
    template = 'Instructions /no_think'
    literal = 'Explain /think and /no_think\n/no_think'
    assert system_instruction(template, native, False) == 'Instructions'
    assert user_instruction(literal, native, False) == literal
    assert user_instruction(literal, native, True) == literal
    assert system_instruction(template, 'qwen3:8b', False) == template
    assert system_instruction(template, 'qwen3:8b', True) == 'Instructions'
    assert user_instruction(literal, 'qwen3:8b', False) == literal + '\n/no_think'
    assert uses_native_controls('library/gemma4:12b')
    assert not uses_native_controls('othergemma4:12b')
    assert not uses_native_controls('qwen3:gemma4')


def test_gemma_native_payload_matches_benchmark_transform_without_data_rewrites(tmp_path, ollama_server, monkeypatch):
    from copilot import llm
    from copilot.storage import Store
    port, seen = ollama_server
    store = Store(tmp_path / 'data.db')
    async def verified(*args):
        pass  # This fake server tests chat payloads, not the independent model verifier.
    monkeypatch.setattr(llm, 'verify_local_model', verified)
    async def scenario():
        async def run(model, question, **extra):
            settings = Settings(model=model, ollama_url=f'http://127.0.0.1:{port}',
                                seed=42, num_ctx=4096, num_predict=1536,
                                history_enabled=False, **extra)
            manager = llm.ChatManager(store, lambda: settings)
            events = [event async for event in manager.stream(question)]
            assert events[-1]['type'] == 'done'
            return seen[-1]
        question = 'Что такое регрессия?'
        legacy = await run('qwen3:8b', question)
        native = await run('gemma4:12b-it-qat', question)
        expected = copy.deepcopy(legacy)
        expected['model'] = 'gemma4:12b-it-qat'
        expected['messages'][0]['content'] = expected['messages'][0]['content'].replace(' /no_think', '').replace(' /think', '')
        expected['messages'][-1]['content'] = expected['messages'][-1]['content'].removesuffix('\n/no_think').removesuffix('\n/think')
        assert native == expected
        assert native['think'] is False
        assert native['options']['seed'] == 42
        assert native['options']['num_ctx'] == 4096
        # Profile and question contain literal switches: only our template changes.
        profile = {'path':'user/profile.md','title':'Profile','text':'User worked with /think and /no_think commands.'}
        monkeypatch.setattr(store, 'profile', lambda: profile)
        monkeypatch.setattr(store, 'search', lambda *args: [])
        question = 'Какие команды /think и /no_think я использовал?\n/think'
        payload = await run('gemma4:12b-it-qat', question)
        assert profile['text'] in payload['messages'][0]['content']
        assert payload['messages'][-1]['content'] == question
        # Native does not silently disable an explicitly enabled reasoning mode.
        thinking = await run('gemma4:12b-it-qat', 'Разбери задачу', reasoning_enabled=True)
        assert thinking['think'] is True
        assert thinking['messages'][-1]['content'] == 'Разбери задачу'
    try:
        asyncio.run(scenario())
    finally:
        store.close()


def test_legacy_seed_is_absent_by_default(tmp_path, ollama_server, monkeypatch):
    from copilot.llm import ChatManager
    from copilot.storage import Store
    port, seen = ollama_server
    store = Store(tmp_path / 'data.db')
    async def scenario():
        settings = Settings(ollama_url=f'http://127.0.0.1:{port}')
        manager = ChatManager(store, lambda: settings)
        events = [event async for event in manager.stream('Вопрос')]
        assert events[-1]['type'] == 'done'
        assert 'seed' not in seen[-1]['options']
        assert seen[-1]['messages'][-1]['content'].endswith('\n/no_think')
    try:
        asyncio.run(scenario())
    finally:
        store.close()
