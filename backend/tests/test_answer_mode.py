from copilot.answer_mode import use_reasoning, needs_profile
from copilot.settings import Settings
import pytest


@pytest.mark.parametrize('question,expected', [
    ('Что такое наблюдаемость?', False),
    ('Какими инструментами ты пользовался?', False),
    ('Что значит консистентность, она всегда обеспечивается автоматически?', True),
    ('Что такое индекс? Когда он мешает?', True),
    ('Что такое HTTP 304?', True),
    ('Что значит `await task()`?', True),
    ('Почему результат отличается?', True),
    ('Разбери проблему приложения.', True),
])
def test_auto_keeps_conditions_code_and_unknown_forms_in_reasoning(question, expected):
    settings = Settings(reasoning_enabled=True, adaptive_reasoning=True)
    assert use_reasoning(question, settings) is expected


def test_explicit_modes_override_auto_for_the_same_question():
    assert not use_reasoning('Почему результат отличается?', Settings(reasoning_enabled=False, adaptive_reasoning=True))
    assert use_reasoning('Что такое наблюдаемость?', Settings(reasoning_enabled=True, adaptive_reasoning=False))


def test_profile_intent_keeps_experience_and_ambiguous_followups():
    assert needs_profile('Какими фреймворками пользовался?', True)
    assert needs_profile('Фреймворки?', True)
    assert needs_profile('Сколько у тебя опыта?', True)
    assert needs_profile('Расскажи подробнее.', False)
    assert not needs_profile('Что означает EXPLAIN ANALYZE в PostgreSQL?', True)
    assert not needs_profile('Почему после перезапуска Pod недоступен?', True)


@pytest.mark.parametrize('question', [
    'Какие фреймворки используешь для тестирования?',
    'Какой фреймворк используете для автоматизации?',
    'Какие языки знаешь?',
    'Какие языки знаете?',
    'На каких языках пишешь автотесты?',
    'Как пишете интеграционные тесты?',
    'С какими языками программирования работаешь?',
    'С чем работаете на проекте?',
    'Какими инструментами пользуешься?',
    'Чем пользуетесь для проверки API?',
    'Что автоматизируешь на текущем проекте?',
    'Что тестируете вручную?',
    'Какими технологиями владеешь?',
    'Расскажи про свой опыт',
])
def test_present_tense_candidate_question_keeps_profile_even_with_technical_reference(question):
    # A matching bundled article must not turn a question about the candidate
    # into a generic explanation without their confirmed skills.
    assert needs_profile(question, True)
    assert needs_profile(question, False)


@pytest.mark.parametrize('question', [
    'Почему Playwright использует изолированные BrowserContext?',
    'Как PostgreSQL использует индекс для поиска?',
    'На каких языках пишут автотесты для веб-приложений?',
    'Какие инструменты используют для нагрузочного тестирования?',
    'Что проверяет регрессионное тестирование?',
    'Как тестируется API без UI?',
    'Какие языки поддерживает Playwright?',
])
def test_third_person_technical_question_does_not_attach_unrelated_profile(question):
    assert not needs_profile(question, True)
    # Missing references still use the conservative ambiguous-question fallback.
    assert needs_profile(question, False)
