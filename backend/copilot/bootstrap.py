"""Locate packaged NVIDIA DLLs before importing CTranslate2. No external download."""
import os
from pathlib import Path
import sys

_dll_handles = []

def configure_runtime():
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    roots = [Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))]
    roots += [Path(item) for item in sys.path if item and Path(item).is_dir()]
    bins = []
    for root in roots:
        for relative in ('nvidia/cublas/bin', 'nvidia/cudnn/bin', 'nvidia/cuda_nvrtc/bin'):
            candidate = root / relative
            if candidate.is_dir() and str(candidate) not in bins:
                bins.append(str(candidate))
                if os.name == 'nt':
                    _dll_handles.append(os.add_dll_directory(str(candidate)))
    if bins:
        os.environ['PATH'] = os.pathsep.join(bins) + os.pathsep + os.environ.get('PATH', '')
    # ONNX Runtime must initialize before WinRT OCR on this Windows build.
    # The opposite order crashes its native initializer with 0xC0000005.
    import onnxruntime
    return bins
