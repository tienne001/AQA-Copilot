import importlib.util
import pytest

def test_storage_module_exists():
    assert importlib.util.find_spec('copilot.storage'), 'persistent local storage not implemented'

def test_russian_history_survives_reopen_and_sessions_are_isolated(tmp_path):
    from copilot.storage import Store
    first = Store(tmp_path / 'data.db')
    a, b = first.new_session(), first.new_session()
    first.add_message(a, 'user', 'Что такое регрессия?')
    first.add_message(a, 'assistant', 'Повторная проверка после изменений.')
    first.add_message(b, 'user', 'Docker')
    first.close()
    reopened = Store(tmp_path / 'data.db')
    assert [m['content'] for m in reopened.history(a)] == ['Что такое регрессия?', 'Повторная проверка после изменений.']
    reopened.clear_history(a)
    assert reopened.history(a) == []
    assert reopened.history(b)[0]['content'] == 'Docker'
    reopened.close()

def test_knowledge_search_handles_russian_and_fts_punctuation(tmp_path):
    from copilot.storage import Store
    store = Store(tmp_path / 'data.db')
    store.import_knowledge('Kafka offsets', 'Kafka: offset — позиция записи в партиции. Смещение сохраняет consumer group.', 'user/kafka.md')
    store.import_knowledge('SQL JOIN', 'LEFT JOIN сохраняет строки левой таблицы.', 'user/sql.md')
    result = store.search('Kafka смещение')
    assert result and result[0]['title'] == 'Kafka offsets'
    assert 'партиции' in result[0]['text']
    assert store.search('" OR * NEAR(') == []
    store.close()

def test_settings_reject_remote_inference_and_invalid_sizes(tmp_path):
    from copilot.settings import Settings, save_settings, load_settings
    for url in ('https://example.com', 'http://127.0.0.1.evil.test:11434', 'http://user:password@127.0.0.1:11434', 'http://127.0.0.1:11434/proxy'):
        with pytest.raises(ValueError):
            Settings(ollama_url=url)
    with pytest.raises(ValueError):
        Settings(num_ctx=99999999)
    value = Settings(model='qwen3:8b', pause_ms=480)
    save_settings(tmp_path, value)
    assert load_settings(tmp_path).pause_ms == 480


def test_pinned_profile_survives_reopen_and_replaces_only_profile(tmp_path):
    from copilot.storage import Store
    path = tmp_path / 'profile.db'
    store = Store(path)
    assert store.profile() is None
    store.import_knowledge('Technical reference', 'Python framework', 'user/reference.md')
    store.import_knowledge('Resume', 'Playwright + TypeScript', 'user/profile.md')
    # A personal question need not contain the technology name.
    assert store.profile()['text'] == 'Playwright + TypeScript'
    store.import_knowledge('Updated resume', 'Playwright, Allure', 'user/profile.md')
    store.close()
    store = Store(path)
    assert store.profile()['text'] == 'Playwright, Allure'
    assert len(store.search('Playwright')) == 1
    assert store.search('Python')[0]['path'] == 'user/reference.md'
    store.close()
