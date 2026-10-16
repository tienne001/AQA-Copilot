"""Package built files without executing them; ZIP64 + CRC verification."""
import argparse
import hashlib
from importlib import metadata
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--exe', type=Path, required=True)
parser.add_argument('--backend', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if not args.exe.is_file() or not (args.backend/'aqa-backend.exe').is_file():
    raise SystemExit('Native application or backend missing')
args.output.parent.mkdir(parents=True, exist_ok=True)
entries = [(args.exe, 'aqa-copilot.exe')]
entries.append((args.source/'build/app-manifest.json', 'application-manifest.json'))
entries += [(path, 'resources/backend/'+path.relative_to(args.backend).as_posix())
            for path in sorted(args.backend.rglob('*')) if path.is_file()]
for name in ('README.md', 'THIRD_PARTY_NOTICES.md'):
    entries.append((args.source/name, name))
entries += [(path, 'testing/'+path.relative_to(args.source/'testing').as_posix())
            for path in sorted((args.source/'testing').rglob('*')) if path.is_file() and path.suffix in ('.py', '.wav')]
for distribution in metadata.distributions():
    name = distribution.metadata.get('Name', 'unknown')
    for item in distribution.files or []:
        if any(word in item.name.lower() for word in ('license', 'copying', 'copyright')):
            path = distribution.locate_file(item)
            if path.is_file() and path.suffix.lower() not in ('.py', '.pyc', '.pyd', '.dll'):
                entries.append((path, 'licenses/'+name+'/'+item.name))
names = set()
with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path, relative in entries:
        target = 'AQA-Copilot/'+relative
        if target in names:
            continue
        names.add(target)
        archive.write(path, target)
    print(f'Packaged {len(names)} files', flush=True)
with zipfile.ZipFile(args.output) as archive:
    broken = archive.testzip()
    if broken:
        raise SystemExit('CRC failure: '+broken)
    for required in ('aqa-copilot.exe','resources/backend/aqa-backend.exe',
                     'resources/backend/_internal/python312.dll',
                     'resources/backend/_internal/faster_whisper/assets/silero_vad_v6.onnx'):
        archive.getinfo('AQA-Copilot/'+required)
digest = hashlib.file_digest(args.output.open('rb'), 'sha256').hexdigest()
args.output.with_suffix('.sha256').write_text(digest+'  '+args.output.name+'\n', encoding='utf-8')
print(f'CRC verified, {args.output.stat().st_size} bytes, SHA256 {digest}', flush=True)
