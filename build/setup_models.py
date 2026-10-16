"""Explicit target-machine setup. Importing this module performs no I/O."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import URLError
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from copilot.model_spec import MODEL_NAME, LOCAL_MODEL_DIGEST, ASR_REPO, ASR_REVISION, ASR_CATALOG, validate_model_name, verified_metadata


def request_json(url, *, local=False, body=None):
    opener = build_opener(ProxyHandler({})) if local else build_opener()
    request = Request(url, data=None if body is None else json.dumps(body).encode('utf-8'), headers={'User-Agent': 'AQA-Copilot-Setup', 'Accept': 'application/json', 'Content-Type': 'application/json'})
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def verified_model(payload, model=MODEL_NAME):
    return verified_metadata(payload, model)


def extract_zip(archive, destination):
    root = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root) or info.filename.startswith(('/', '\\')):
                raise RuntimeError('Unsafe path in downloaded archive')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('Symlink in downloaded archive')
        source.extractall(root)


def ensure_ollama(data):
    target = data / 'tools' / 'ollama'
    executable = target / 'ollama.exe'
    if executable.is_file():
        return executable
    if target.exists():
        raise RuntimeError(f'Incomplete installation at {target}; rename it and rerun setup.')
    release = request_json('https://api.github.com/repos/ollama/ollama/releases/latest')
    asset = next((a for a in release['assets'] if a['name'] == 'ollama-windows-amd64.zip'), None)
    if not asset or not str(asset.get('digest', '')).startswith('sha256:'):
        raise RuntimeError('Official Ollama release is missing a Windows ZIP with SHA256 digest.')
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/ollama/ollama/releases/download/'):
        raise RuntimeError('Unexpected Ollama download origin')
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / 'ollama-download.zip'
    partial = archive.with_suffix('.partial')
    print(f"Downloading portable Ollama {release['tag_name']}...", flush=True)
    with build_opener().open(Request(url, headers={'User-Agent': 'AQA-Copilot-Setup'}), timeout=120) as response:
        with partial.open('wb') as output:
            shutil.copyfileobj(response, output, 1024 * 1024)
    with partial.open('rb') as downloaded:
        actual = hashlib.file_digest(downloaded, 'sha256').hexdigest()
    if actual != asset['digest'].split(':', 1)[1]:
        raise RuntimeError('Ollama ZIP checksum mismatch; archive was not extracted.')
    partial.replace(archive)
    staging = target.parent / ('ollama-staging-' + uuid.uuid4().hex)
    extract_zip(archive, staging)
    if not (staging / 'ollama.exe').is_file():
        raise RuntimeError('Official ZIP did not contain ollama.exe')
    (staging / 'installed-release.json').write_text(json.dumps({
        'version': release['tag_name'], 'sha256': actual, 'url': url}, indent=2), encoding='utf-8')
    staging.rename(target)
    archive.unlink()
    return executable


def write_initial_settings(data, device, model=MODEL_NAME, asr_model='medium', update=False):
    settings = data / 'settings.json'
    validate_model_name(model)
    if asr_model not in ASR_CATALOG:
        raise ValueError('Unknown Whisper model')
    initial = {'model': model, 'asr_model_path': str(data / 'models' / ('whisper-' + asr_model)),
               'asr_device': device, 'asr_compute_type': 'int8_float16' if device == 'cuda' else 'int8'}
    # Exclusive create: never overwrite an existing user's settings.
    try:
        with settings.open('x', encoding='utf-8') as output:
            json.dump(initial, output, indent=2, ensure_ascii=False)
    except FileExistsError:
        if update:
            original = json.loads(settings.read_text(encoding='utf-8-sig'))
            original.update(initial)
            backup = data / ('settings.backup-' + uuid.uuid4().hex + '.json')
            shutil.copy2(settings, backup)
            temporary = data / ('settings-' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps(original, indent=2, ensure_ascii=False), encoding='utf-8')
            temporary.replace(settings)
    return json.loads(settings.read_text(encoding='utf-8-sig'))


def ensure_qwen(executable, data, model=MODEL_NAME):
    validate_model_name(model)
    # Do not reuse/stop a daemon that might belong to another app or model directory.
    with socket.socket() as probe:
        if os.name == 'nt':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', 11435))
        except OSError as error:
            raise RuntimeError('Port 11435 is occupied. Close AQA Copilot before model setup.') from error
    environment = dict(os.environ, OLLAMA_HOST='127.0.0.1:11435',
                       OLLAMA_MODELS=str(data / 'models' / 'ollama'), OLLAMA_NO_CLOUD='1',
                       OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1')
    with (data / 'ollama-setup.log').open('ab') as log:
        process = subprocess.Popen([str(executable), 'serve'], env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 45
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Ollama exited; see ollama-setup.log')
                try:
                    payload = request_json('http://127.0.0.1:11435/api/tags', local=True)
                    break
                except (URLError, TimeoutError, OSError):
                    if time.monotonic() > deadline:
                        raise RuntimeError('Ollama did not start within 45 seconds')
                    time.sleep(.3)
            if not verified_model(payload, model):
                print(f'Downloading {model} (interrupted pulls can be resumed)...', flush=True)
                subprocess.run([str(executable), 'pull', model], env=environment, check=True)
                payload = request_json('http://127.0.0.1:11435/api/tags', local=True)
                if not verified_model(payload, model):
                    raise RuntimeError('Downloaded model did not pass local metadata verification. No inference was run.')
            from copilot.model_spec import MODEL_CATALOG
            if model not in MODEL_CATALOG:
                details = request_json('http://127.0.0.1:11435/api/show', local=True, body={'model': model})
                if 'completion' not in details.get('capabilities', []):
                    raise RuntimeError('Selected model cannot generate answers. Choose a chat/completion model.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--asr-device', choices=['cuda', 'cpu'], default='cuda')
    parser.add_argument('--model', default=MODEL_NAME, type=validate_model_name)
    parser.add_argument('--asr-model', choices=ASR_CATALOG, default='medium')
    parser.add_argument('--update-settings', action='store_true', help='Back up and apply explicitly selected model/device options')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This setup targets Windows x64.')
    data = args.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=True)
    settings = write_initial_settings(data, args.asr_device, args.model, args.asr_model, args.update_settings)
    model = settings.get('model', args.model)
    whisper = Path(settings.get('asr_model_path') or data / 'models' / 'whisper-medium')
    if not whisper.is_absolute() or str(whisper).startswith(('\\\\', '//')):
        raise RuntimeError('The configured ASR model directory must be an absolute local path.')
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ.pop('HF_HUB_OFFLINE', None)
    from huggingface_hub import snapshot_download
    asr_choice = args.asr_model if args.update_settings else next((name for name in ASR_CATALOG if whisper.name == 'whisper-' + name), args.asr_model)
    repo, revision = ASR_CATALOG[asr_choice]
    print(f'Downloading/verifying {repo} at {revision}...', flush=True)
    snapshot_download(repo, revision=revision, local_dir=str(whisper), token=False,
                      allow_patterns=['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*', 'preprocessor_config.json'])
    for name in ['config.json', 'model.bin', 'tokenizer.json']:
        if not (whisper / name).is_file() or (whisper / name).stat().st_size == 0:
            raise RuntimeError(f'Incomplete Whisper model: {name}')
    if not any(whisper.glob('vocabulary.*')):
        raise RuntimeError('Incomplete Whisper model: vocabulary missing')
    ensure_qwen(ensure_ollama(data), data, model)
    print('Model files verified. Setup daemon stopped. Inference/GPU performance was not tested.', flush=True)


if __name__ == '__main__':
    main()
