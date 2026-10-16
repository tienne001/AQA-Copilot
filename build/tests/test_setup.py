import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('setup_models', ROOT / 'build/setup_models.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def good_metadata():
    return {'models': [{'name': setup.MODEL_NAME, 'digest': setup.LOCAL_MODEL_DIGEST,
                        'size': 5225388164, 'details': {'format': 'gguf', 'family': 'qwen3'}}]}


class SetupTests(unittest.TestCase):
    def test_model_rejects_changed_digest_and_cloud(self):
        self.assertTrue(setup.verified_model(good_metadata()))
        for change in [{'digest': 'bad'}, {'remote_host': 'https://example.test'}, {'size': 0}]:
            payload = good_metadata()
            payload['models'][0].update(change)
            self.assertFalse(setup.verified_model(payload))

    def test_initial_settings_are_portable_and_preserved_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            first = setup.write_initial_settings(data, 'cpu')
            self.assertEqual(first['asr_model_path'], str(data / 'models/whisper-medium'))
            self.assertEqual(first['asr_compute_type'], 'int8')
            custom = {'asr_model_path': str(data / 'custom'), 'num_predict': 160}
            (data / 'settings.json').write_text(json.dumps(custom), encoding='utf-8')
            self.assertEqual(setup.write_initial_settings(data, 'cuda'), custom)

    def test_archive_traversal_rejected_before_any_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'download.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('ollama.exe', 'fake')
                output.writestr('../escape.txt', 'bad')
            with self.assertRaises(RuntimeError):
                setup.extract_zip(archive, root / 'target')
            self.assertFalse((root / 'escape.txt').exists())
            self.assertFalse((root / 'target/ollama.exe').exists())

    def test_existing_portable_ollama_does_not_download(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            exe = data / 'tools/ollama/ollama.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'test')
            with patch.object(setup, 'request_json', side_effect=AssertionError('network')):
                self.assertEqual(setup.ensure_ollama(data), exe)

    def test_busy_port_never_starts_or_stops_a_daemon(self):
        with patch.object(setup.socket, 'socket') as sockets, patch.object(setup.subprocess, 'Popen') as spawn:
            sockets.return_value.__enter__.return_value.bind.side_effect = OSError('busy')
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                setup.ensure_qwen(Path('ollama.exe'), Path('.'))
            spawn.assert_not_called()

    def test_existing_verified_model_skips_pull_and_stops_owned_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(setup.socket, 'socket'), patch.object(setup, 'request_json', return_value=good_metadata()), patch.object(setup.subprocess, 'Popen') as spawn, patch.object(setup.subprocess, 'run') as pull:
                process = spawn.return_value
                process.poll.return_value = None
                setup.ensure_qwen(Path('ollama.exe'), Path(directory))
                pull.assert_not_called()
                process.terminate.assert_called_once()
                self.assertEqual(spawn.call_args.kwargs['env']['OLLAMA_HOST'], '127.0.0.1:11435')
                self.assertEqual(spawn.call_args.kwargs['env']['OLLAMA_MODELS'], str(Path(directory) / 'models/ollama'))

    def test_backend_defaults_use_supplied_data_directory(self):
        from copilot.settings import load_settings
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(directory)
            self.assertEqual(Path(settings.asr_model_path), Path(directory).resolve() / 'models/whisper-medium')

    def test_explicit_model_update_keeps_other_settings_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            previous = {'model':'qwen3:8b','num_predict':256,'history_enabled':False}
            (data/'settings.json').write_text(json.dumps(previous), encoding='utf-8')
            changed = setup.write_initial_settings(data, 'cpu', 'qwen3:4b', 'small', update=True)
            self.assertEqual(changed['model'], 'qwen3:4b')
            self.assertEqual(changed['num_predict'], 256)
            self.assertFalse(changed['history_enabled'])
            self.assertEqual(Path(changed['asr_model_path']),data/'models/whisper-small')
            backups=list(data.glob('settings.backup-*.json'))
            self.assertEqual(len(backups),1)
            self.assertEqual(json.loads(backups[0].read_text()),previous)

    def test_failed_pull_still_stops_only_owned_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(setup.socket, 'socket'), patch.object(setup, 'request_json', return_value={'models': []}), patch.object(setup.subprocess, 'Popen') as spawn, patch.object(setup.subprocess, 'run', side_effect=RuntimeError('download failed')):
                process = spawn.return_value
                process.poll.return_value = None
                with self.assertRaisesRegex(RuntimeError, 'download failed'):
                    setup.ensure_qwen(Path('ollama.exe'), Path(directory))
                process.terminate.assert_called_once()

    def test_source_export_excludes_runtime_data_and_dependencies(self):
        export_spec = importlib.util.spec_from_file_location('export_sources', ROOT / 'build/export_sources.py')
        export = importlib.util.module_from_spec(export_spec)
        export_spec.loader.exec_module(export)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in export.ROOT_FILES:
                (root / name).write_text('source', encoding='utf-8')
            for name in ['frontend/src/App.tsx', 'frontend/node_modules/large.json', 'frontend/src-tauri/target/artifact.json', 'backend/data/private.json', 'backend/copilot/settings.json', 'backend/copilot/service.py']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('example', encoding='utf-8')
            exported = {p.relative_to(root).as_posix() for p in export.source_files(root)}
            self.assertEqual(exported - export.ROOT_FILES, {'frontend/src/App.tsx', 'backend/copilot/service.py'})


if __name__ == '__main__':
    unittest.main()
