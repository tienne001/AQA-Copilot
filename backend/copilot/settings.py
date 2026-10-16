"""Validated on-disk configuration. Inference destinations are literal loopback only."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .model_spec import validate_model_name


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = 'qwen3:8b'
    ollama_url: str = 'http://127.0.0.1:11435'
    asr_model_path: str = ''
    asr_device: str = 'cuda'
    asr_compute_type: str = 'int8_float16'
    pause_ms: int = Field(default=480, ge=160, le=5000)
    temperature: float = Field(default=.2, ge=0, le=1)
    num_ctx: int = Field(default=4096, ge=1024, le=16384)
    num_predict: int = Field(default=512, ge=32, le=4096)
    # None preserves existing runtime sampling; an explicit value reproduces benchmarks.
    seed: int | None = Field(default=None, strict=True, ge=0, le=2147483647)
    reasoning_enabled: bool = False
    adaptive_reasoning: bool = False
    online_reference_enabled: bool = False
    auto_answer: bool = True
    microphone_auto_answer: bool = False
    verified_answer_cards_enabled: bool = False
    knowledge_enabled: bool = True
    history_enabled: bool = True
    vram_reserve_mb: int = Field(default=1536, ge=512, le=8192)
    tesseract_path: str = ''

    @field_validator('ollama_url')
    @classmethod
    def loopback_only(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or
                parsed.username or parsed.password or parsed.path not in ('', '/') or
                parsed.query or parsed.fragment or not parsed.port):
            raise ValueError('Ollama должна использовать http и IP loopback с портом, без прокси/пути')
        return value.rstrip('/')

    @field_validator('model')
    @classmethod
    def valid_model(cls, value):
        return validate_model_name(value)

    @field_validator('asr_device')
    @classmethod
    def valid_device(cls, value):
        if value not in ('cuda', 'cpu'):
            raise ValueError('ASR device: cuda или cpu')
        return value

    @field_validator('asr_compute_type')
    @classmethod
    def valid_compute(cls, value):
        if value not in ('int8_float16', 'float16', 'int8', 'float32'):
            raise ValueError('Недопустимый режим вычисления ASR')
        return value

    @field_validator('asr_model_path', 'tesseract_path')
    @classmethod
    def local_paths(cls, value):
        if '\x00' in value or value.startswith(('\\\\', '//', 'http:', 'https:')):
            raise ValueError('Нужен путь на локальном диске')
        if value and not Path(value).is_absolute():
            raise ValueError('Нужен абсолютный локальный путь')
        return value


def load_settings(data_dir):
    path = Path(data_dir) / 'settings.json'
    if path.exists():
        return Settings.model_validate_json(path.read_text(encoding='utf-8'))
    return Settings(asr_model_path=str((Path(data_dir) / 'models' / 'whisper-medium').resolve()))


def save_settings(data_dir, settings):
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / 'settings.json.tmp'
    temporary.write_text(settings.model_dump_json(indent=2), encoding='utf-8')
    os.replace(temporary, directory / 'settings.json')
