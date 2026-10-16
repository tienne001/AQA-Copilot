# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs
import PyInstaller.building.build_main as build_main

# Windows ONNX Runtime 1.31 crashes (0xC0000005) if WinRT initializes first.
# Reproduced in a clean Python subprocess; preserve the same safe order in the
# dependency-scanner process as bootstrap.py uses in the application.
_find_dependencies = build_main.find_binary_dependencies
def ordered_dependencies(binaries, packages, suppression):
    packages = sorted(packages, key=lambda name: (not name.startswith('onnxruntime'), name))
    return _find_dependencies(binaries, packages, suppression)
build_main.find_binary_dependencies = ordered_dependencies

source = Path(SPECPATH).parent/'backend'
site = Path(sys.prefix)/'Lib/site-packages'
datas = [(str(source/'knowledge'), 'knowledge'), (str(source/'fixtures'), 'fixtures')]
datas.append((str(source/'answer_cards'), 'answer_cards'))
binaries, hiddenimports = [], []
for package in ('faster_whisper','tokenizers','winrt'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
for package in ('ctranslate2','onnxruntime'):
    binaries += collect_dynamic_libs(package)
    datas += collect_data_files(package, includes=['**/*.json','**/*.onnx'])
hiddenimports += ['ctranslate2._ext','onnxruntime.capi._pybind_state']
for component in ('cublas','cudnn','cuda_nvrtc'):
    directory = site/'nvidia'/component/'bin'
    binaries += [(str(path), f'nvidia/{component}/bin') for path in directory.glob('*.dll')]
hiddenimports += ['winrt.windows.foundation.collections','winrt.windows.foundation','winrt.windows.globalization',
    'winrt.windows.media.ocr','winrt.windows.graphics.imaging','winrt.windows.storage.streams','winrt.windows.storage',
    'uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on']
a = Analysis([str(source/'run_backend.py')], pathex=[str(source)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports, excludes=['torch','tensorflow','matplotlib','IPython',
                 'onnxruntime.quantization','onnxruntime.transformers','onnxruntime.tools','ctranslate2.converters'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='aqa-backend',debug=False,bootloader_ignore_signals=False,
          strip=False,upx=False,console=False,disable_windowed_traceback=False)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='aqa-backend')
