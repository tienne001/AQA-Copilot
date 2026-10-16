# Сторонние компоненты

Сборка использует Tauri, React, Python, FastAPI, faster-whisper, CTranslate2, ONNX Runtime, Silero VAD, PyAudioWPatch, NumPy/SciPy, Pillow, WinRT и NVIDIA CUDA/cuDNN runtime. Исходные уведомления о лицензиях Python-пакетов и NVIDIA wheels, доступные в установленной среде сборки, включены в переносимый ZIP в папке `licenses`.

Официальные проекты: [Tauri](https://github.com/tauri-apps/tauri), [React](https://github.com/facebook/react), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [Silero VAD](https://github.com/snakers4/silero-vad), [ONNX Runtime](https://github.com/microsoft/onnxruntime), [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch), [NVIDIA cuDNN](https://developer.nvidia.com/cudnn).

Ollama, модель Qwen3 8B и веса faster-whisper Medium устанавливаются отдельно через Setup.ps1 и не включены в архив приложения. Их исходники, карточки моделей и условия: [Ollama](https://github.com/ollama/ollama), [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), [faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium).

Microsoft Windows OCR и WebView2 предоставляются установленными компонентами Windows. Сборка не подписана издательским сертификатом.
# Selected application icon

The Logitech G HUB icon was selected by the project owner. Source:
https://www.logitech.com/assets/65549/lg-hub-logo.png
Logitech and G HUB marks belong to Logitech. This independent application is not affiliated with Logitech.

## Current local profile

The current deployment uses the local Ollama tag gemma4:12b-it-qat and Whisper large-v3. No model weights or Ollama binaries are included in this source snapshot. Their applicable terms remain separate.
