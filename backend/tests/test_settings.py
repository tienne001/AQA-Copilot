import json

import pytest

from copilot.settings import Settings, load_settings, save_settings


def test_old_settings_without_reasoning_field_keep_the_previous_default(tmp_path):
    previous = Settings().model_dump()
    previous.pop('reasoning_enabled')
    (tmp_path / 'settings.json').write_text(json.dumps(previous), encoding='utf-8')
    restored = load_settings(tmp_path)
    assert restored.reasoning_enabled is False
    assert restored.num_predict == previous['num_predict']


def test_reasoning_and_4096_token_limit_round_trip_without_touching_other_settings(tmp_path):
    settings = Settings(reasoning_enabled=True, num_predict=4096, num_ctx=8192)
    save_settings(tmp_path, settings)
    restored = load_settings(tmp_path)
    assert restored.reasoning_enabled is True
    assert restored.num_predict == 4096
    assert restored.asr_device == settings.asr_device
    assert restored.asr_model_path == settings.asr_model_path
    assert restored.history_enabled == settings.history_enabled


@pytest.mark.parametrize('tokens', [-1, 0, 31, 4097, 100000])
def test_generation_limit_rejects_unbounded_and_out_of_range_values(tokens):
    with pytest.raises(ValueError):
        Settings(num_predict=tokens)
