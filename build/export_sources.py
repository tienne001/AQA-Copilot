"""Create a source-only ZIP from an explicit list of source trees."""
import argparse
import hashlib
import os
from pathlib import Path
import zipfile

ROOT_FILES = {'.gitignore', '.gitattributes', 'README.md', 'THIRD_PARTY_NOTICES.md', 'Setup.ps1', 'Setup.cmd'}
TREES = {'backend', 'build', 'frontend', 'installer', 'testing'}
EXCLUDED = {'node_modules', '.npm-cache', 'dist', 'target', 'gen', 'resources', '__pycache__',
            '.pytest_cache', '.venv', 'venv', 'data', 'models', '.git'}
EXTENSIONS = {'.py', '.txt', '.md', '.wav', '.ps1', '.spec', '.json', '.toml', '.lock',
              '.rs', '.ts', '.tsx', '.mjs', '.css', '.html', '.png', '.ico', '.cs', '.manifest'}


def source_files(root):
    for name in sorted(ROOT_FILES):
        path = root / name
        if not path.is_file():
            raise RuntimeError(f'Required source file missing: {name}')
        yield path
    for tree in sorted(TREES):
        for current, directories, files in os.walk(root / tree):
            directories[:] = sorted(d for d in directories if d not in EXCLUDED and not d.startswith('.'))
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix in EXTENSIONS and name != 'settings.json' and not path.is_symlink():
                    yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = list(source_files(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'AqaCopilot/' + path.relative_to(root).as_posix())
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip():
            raise RuntimeError('Source archive CRC failed')
    with args.output.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    args.output.with_suffix('.sha256').write_text(digest + '  ' + args.output.name + '\n', encoding='utf-8')
    print(f'Source archive: {len(files)} files, {args.output.stat().st_size} bytes; CRC OK; SHA256 {digest}')


if __name__ == '__main__':
    main()
