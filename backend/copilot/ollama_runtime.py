"""Start the installed Ollama locally when the application's private port is absent."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import time
import httpx

from .model_spec import LOCAL_MODEL_DIGEST, MODEL_CATALOG, verified_metadata


def verify_local_metadata(payload, model):
    if not verified_metadata(payload, model):
        raise RuntimeError(f'Локальная модель {model} не подтверждена. Проверьте установку; облачные модели запрещены.')


async def verify_local_model(client, url, model):
    # Validate downloaded manifest before sending any dialogue/OCR/knowledge text.
    response = await client.get(url + '/api/tags')
    response.raise_for_status()
    verify_local_metadata(response.json(), model)
    if model not in MODEL_CATALOG:
        details = await client.post(url + '/api/show', json={'model': model})
        details.raise_for_status()
        if 'completion' not in details.json().get('capabilities', []):
            raise RuntimeError('Выбранная модель не поддерживает генерацию ответов. Выберите chat/completion-модель.')


class OllamaRuntime:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.process = None
        self.lock = asyncio.Lock()

    async def ensure(self, url):
        async with self.lock:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                try:
                    response = await client.get(url + '/api/version')
                    response.raise_for_status()
                    return
                except httpx.HTTPError as error:
                    if url != 'http://127.0.0.1:11435':
                        raise RuntimeError('Настроенная Ollama недоступна: ' + str(error)) from error
                portable = self.data_dir / 'tools' / 'ollama' / 'ollama.exe'
                executable = str(portable) if portable.is_file() else shutil.which('ollama')
                if not executable:
                    candidate = Path.home() / 'AppData/Local/Programs/Ollama/ollama.exe'
                    if candidate.is_file():
                        executable = str(candidate)
                if not executable:
                    raise RuntimeError('Ollama не найдена. Выполните Setup.ps1 -Mode Models на целевом компьютере.')
                if self.process is None or self.process.poll() is not None:
                    environment = dict(os.environ)
                    environment.update(OLLAMA_HOST='127.0.0.1:11435',
                        OLLAMA_MODELS=str((self.data_dir / 'models' / 'ollama').resolve()),
                        OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1',
                        OLLAMA_FLASH_ATTENTION='1', OLLAMA_KV_CACHE_TYPE='q8_0', OLLAMA_NO_CLOUD='1',
                        LLAMA_ARG_CACHE_RAM='1024')
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    with (self.data_dir/'ollama.log').open('ab') as log:
                        self.process = subprocess.Popen([executable, 'serve'], env=environment,
                            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError('Ollama завершилась при запуске; проверьте локальный ollama.log')
                    try:
                        response = await client.get(url+'/api/version')
                        response.raise_for_status()
                        return
                    except httpx.HTTPError:
                        await asyncio.sleep(.2)
                raise RuntimeError('Ollama не ответила за 15 секунд')

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
