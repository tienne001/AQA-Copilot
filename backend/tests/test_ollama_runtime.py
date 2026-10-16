import asyncio
import pytest

def test_cloud_names_are_rejected_before_any_prompt_is_sent():
    from copilot.settings import Settings
    for model in ('gemma4:cloud', 'qwen3:cloud', 'qwen3', '../qwen:8b', 'qwen3:4b;calc', 'https://example.test/x:latest'):
        with pytest.raises(ValueError):
            Settings(model=model)

def test_catalog_and_custom_local_tags_are_supported():
    from copilot.settings import Settings
    for model in ('qwen3:1.7b', 'qwen3:4b', 'qwen3:8b', 'qwen3:14b', 'qwen2.5-coder:7b', 'user/local-model:latest'):
        assert Settings(model=model).model == model

def test_each_catalog_model_checks_its_own_digest():
    from copilot.model_spec import MODEL_CATALOG, verified_metadata
    for name, (digest, minimum) in MODEL_CATALOG.items():
        entry = {'name': name, 'digest': digest, 'size': minimum, 'details': {'format':'gguf','family':'qwen3'}}
        assert verified_metadata({'models':[entry]}, name)
        assert not verified_metadata({'models':[{**entry, 'digest':'0'*64}]}, name)

def test_custom_model_requires_local_gguf_and_full_digest():
    from copilot.model_spec import verified_metadata
    entry = {'name':'user/model:latest','digest':'a'*64,'size':100,'details':{'format':'gguf'}}
    assert verified_metadata({'models':[entry]}, entry['name'])
    assert not verified_metadata({'models':[{**entry,'remote_model':'remote'}]}, entry['name'])

def test_cloud_or_unverified_metadata_is_rejected():
    from copilot.ollama_runtime import verify_local_metadata, LOCAL_MODEL_DIGEST
    good = {'name':'qwen3:8b','digest':LOCAL_MODEL_DIGEST,'size':5225388164,
            'details':{'format':'gguf','family':'qwen3'}}
    verify_local_metadata({'models':[good]}, 'qwen3:8b')
    for bad in ({**good,'digest':'unknown'}, {**good,'remote_host':'https://ollama.com'},
                {**good,'size':0}, {**good,'details':{'format':'cloud','family':'qwen3'}}):
        with pytest.raises(RuntimeError):
            verify_local_metadata({'models':[bad]}, 'qwen3:8b')

def test_custom_unavailable_server_is_not_replaced_by_an_implicit_daemon(tmp_path):
    from copilot.ollama_runtime import OllamaRuntime
    async def scenario():
        daemon = OllamaRuntime(tmp_path)
        with pytest.raises(RuntimeError, match='недоступна'):
            await daemon.ensure('http://127.0.0.1:1')
        assert daemon.process is None
    asyncio.run(scenario())


@pytest.mark.parametrize('redirected', [False, True])
def test_private_daemon_caps_prompt_cache_in_child_environment_only(tmp_path, monkeypatch, redirected):
    import os
    import httpx
    from copilot import ollama_runtime
    monkeypatch.setenv('LLAMA_ARG_CACHE_RAM', '8192')
    monkeypatch.setenv('COPILOT_TEST_INHERITED_FLAG', 'preserved')
    portable = tmp_path / 'tools' / 'ollama' / 'ollama.exe'
    portable.parent.mkdir(parents=True)
    portable.write_bytes(b'not an executable; Popen is mocked')
    launches = []
    model_path = tmp_path / 'models' / 'ollama'
    model_path.parent.mkdir()
    target = tmp_path / 'relocated-models' if redirected else model_path
    target.mkdir()
    (target / 'manifest-marker').write_text('relocated store', encoding='utf-8')
    if redirected:
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(target), str(model_path))
        else:
            model_path.symlink_to(target, target_is_directory=True)
        assert model_path.resolve() == target.resolve()
        assert str(model_path) != str(target.resolve())

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        launches.append((command, kwargs))
        return FakeProcess()

    def request(request):
        assert str(request.url) == 'http://127.0.0.1:11435/api/version'
        if not launches:
            raise httpx.ConnectError('private server not started', request=request)
        return httpx.Response(200, json={'version': 'test'})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(ollama_runtime.httpx, 'AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(request), **kwargs))
    monkeypatch.setattr(ollama_runtime.subprocess, 'Popen', fake_popen)
    daemon = ollama_runtime.OllamaRuntime(tmp_path)
    asyncio.run(daemon.ensure('http://127.0.0.1:11435'))
    assert len(launches) == 1
    command, options = launches[0]
    assert command == [str(portable), 'serve']
    assert options['env']['LLAMA_ARG_CACHE_RAM'] == '1024'
    assert options['env']['OLLAMA_HOST'] == '127.0.0.1:11435'
    assert options['env']['OLLAMA_MODELS'] == str(target.resolve())
    from pathlib import Path
    actual_store = Path(options['env']['OLLAMA_MODELS'])
    assert (actual_store / 'manifest-marker').read_text(encoding='utf-8') == 'relocated store'
    if redirected:
        assert options['env']['OLLAMA_MODELS'] != str(model_path)
    assert options['env']['COPILOT_TEST_INHERITED_FLAG'] == 'preserved'
    assert os.environ['LLAMA_ARG_CACHE_RAM'] == '8192'
    assert daemon.process is not None


def test_healthy_existing_server_is_used_without_launch_or_environment_changes(tmp_path, monkeypatch):
    import os
    import httpx
    from copilot import ollama_runtime
    monkeypatch.setenv('LLAMA_ARG_CACHE_RAM', '8192')

    def request(request):
        assert str(request.url) == 'http://127.0.0.1:11435/api/version'
        return httpx.Response(200, json={'version': 'existing'})

    def forbidden_launch(*args, **kwargs):
        pytest.fail('A healthy existing server must not be launched or reconfigured')

    original_client = httpx.AsyncClient
    monkeypatch.setattr(ollama_runtime.httpx, 'AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(request), **kwargs))
    monkeypatch.setattr(ollama_runtime.subprocess, 'Popen', forbidden_launch)
    data_dir = tmp_path / 'unchanged'
    daemon = ollama_runtime.OllamaRuntime(data_dir)
    asyncio.run(daemon.ensure('http://127.0.0.1:11435'))
    assert daemon.process is None
    assert not data_dir.exists()
    assert os.environ['LLAMA_ARG_CACHE_RAM'] == '8192'
