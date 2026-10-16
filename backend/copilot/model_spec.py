"""Shared model identity for setup and runtime verification."""
MODEL_NAME = 'qwen3:8b'
LOCAL_MODEL_DIGEST = '500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41'
ASR_REPO = 'Systran/faster-whisper-medium'
ASR_REVISION = '7832330bcea9a8d5fd6d6637c49fe5d256e98277'

MODEL_CATALOG = {
    'qwen3:1.7b': ('8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7', 1_000_000_000),
    'qwen3:4b': ('359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7', 2_000_000_000),
    MODEL_NAME: (LOCAL_MODEL_DIGEST, 4_000_000_000),
    'qwen3:14b': ('bdbd181c33f2ed1b31c972991882db3cf4d192569092138a7d29e973cd9debe8', 8_000_000_000),
}
ASR_CATALOG = {
    'tiny': ('Systran/faster-whisper-tiny', 'd90ca5fe260221311c53c58e660288d3deb8d356'),
    'base': ('Systran/faster-whisper-base', 'ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66'),
    'small': ('Systran/faster-whisper-small', '536b0662742c02347bc0e980a01041f333bce120'),
    'medium': (ASR_REPO, ASR_REVISION),
    'large-v3': ('Systran/faster-whisper-large-v3', 'edaa852ec7e145841d8ffdb056a99866b5f0a478'),
}

def validate_model_name(value):
    import re
    if (not isinstance(value, str) or len(value) > 160 or 'cloud' in value.lower()
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*(?:/[a-zA-Z0-9][a-zA-Z0-9_.-]*)?:[a-zA-Z0-9][a-zA-Z0-9_.-]*', value)):
        raise ValueError('Укажите локальную модель Ollama с тегом, например qwen3:4b. Облачные модели запрещены.')
    return value

def verified_metadata(payload, model):
    import re
    validate_model_name(model)
    entry = next((item for item in payload.get('models', []) if item.get('name') == model), None)
    if (not entry or entry.get('remote_host') or entry.get('remote_model')
            or entry.get('details', {}).get('format') != 'gguf'
            or entry.get('size', 0) <= 0
            or not re.fullmatch(r'[0-9a-f]{64}', entry.get('digest', ''))):
        return False
    if model in MODEL_CATALOG:
        digest, minimum = MODEL_CATALOG[model]
        return entry['digest'] == digest and entry['size'] >= minimum and entry['details'].get('family') == 'qwen3'
    # Advanced local models have no catalog pin, but must be present as a local GGUF.
    return True
