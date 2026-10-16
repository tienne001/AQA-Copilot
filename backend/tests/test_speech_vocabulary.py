"""Regression cases from real ASR failures plus the supplied vacancy stack."""
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from copilot.audio import SpeechEngine
from copilot.speech_vocabulary import AQA_HOTWORDS, VOCABULARY, normalize_technical_terms


@pytest.mark.parametrize(('spoken', 'expected'), [
    ('Расскажи, пожалуйста, что такое чмот и что такое човно.',
     'Расскажи, пожалуйста, что такое chmod и что такое chown.'),
    ('Чем отличаются ЧМОД и ЧОУН?', 'Чем отличаются chmod и chown?'),
    ('Что делают h-mod и h-own?', 'Что делают chmod и chown?'),
    ('постгрес, рэббит эм кью и кафка', 'PostgreSQL, RabbitMQ и Kafka'),
    ('языки: питон, си шарп и си плюс плюс', 'языки: Python, C# и C++'),
    ('спринг бут, котлин, джава и груви', 'Spring Boot, Kotlin, Java и Groovy'),
    ('тайп скрипт, джава скрипт, npm, нода, ант и редакс',
     'TypeScript, JavaScript, npm, Node.js, Ant и Redux'),
    ('джира, тест рейл, дженкинс, конфлюенс, битбакет, фигма и слак',
     'Jira, TestRail, Jenkins, Confluence, Bitbucket, Figma и Slack'),
    ('докер компоуз, кубернетес, ви эм вэр и виртуал бокс',
     'Docker Compose, Kubernetes, VMware и VirtualBox'),
    ('линукс, баш, гит, он премис и стек трейс', 'Linux, Bash, Git, on-premise и stack trace'),
    ('Модель оси, ти си пи ай пи, ди эн эс, ю ди пи, эйч ти ти пи эс',
     'модель OSI, TCP/IP, DNS, UDP, HTTPS'),
    ('эс кью эл, лефт джоин, груп бай, хэвинг и эксплейн',
     'SQL, LEFT JOIN, GROUP BY, HAVING и EXPLAIN'),
    ('джава-скрипт, тайп   скрипт, тест-рейл', 'JavaScript, TypeScript, TestRail'),
    ('K8s, js, NodeJS, POSTGRES', 'Kubernetes, JavaScript, Node.js, PostgreSQL'),
    ('Тесткейсы лежат в TestRail, задачи в Jiri.', 'test cases лежат в TestRail, задачи в Jira.'),
    ('Docker, Compose и TCPIP.', 'Docker Compose и TCP/IP.'),
    ('Формат джейсон и код на питоне.', 'Формат JSON и код на Python.'),
    ('Работа в PostgreSQL, RabbitMQ, C#, C++.', 'Работа в PostgreSQL, RabbitMQ, C#, C++.'),
])
def test_known_phonetic_transcriptions(spoken, expected):
    corrected, changes = normalize_technical_terms(spoken)
    assert corrected == expected
    assert normalize_technical_terms(corrected)[0] == expected
    assert all(item['from'] != item['to'] for item in changes)


@pytest.mark.parametrize('text', [
    'Купил чмот и пошёл домой.',
    'Поворот вокруг оси и новая реплика в разговоре.',
    'Расскажи, что такое чмот в игре.',
    'Расскажи, пожалуйста, какой чмот купить в дорогу.',
    'В зоопарке питон, а продюсер фильма сказал привет.',
    'Джейсон попросил проверить Jira.',
    'Почему нода Kubernetes находится в состоянии NotReady?',
    'Файл "докер.txt" и "питон.py", а также "java.py".',
    'https://example.test/?engine=python&tool=docker',
    '`python -c "print(1)"` и `докер`',
    'Чем отличается регресс от повторной проверки исправления?',
    'Ретроспектива релиза, микросервисы, виртуализация и сложные системы.',
    'классификация, докеризация, джираф, питонист, javascriptify',
    '/home/чмод /tmp/питон C:\\чоун\\file.txt https://example.test/чмод',
    '',
])
def test_does_not_rewrite_unrelated_words_paths_or_already_correct_russian(text):
    assert normalize_technical_terms(text) == (text, [])


def test_aliases_are_unambiguous_and_all_reachable():
    aliases_seen = {}
    for canonical, aliases in VOCABULARY:
        assert normalize_technical_terms(canonical)[0] == canonical
        for alias in aliases:
            assert aliases_seen.setdefault(alias.casefold(), canonical) == canonical
            assert normalize_technical_terms(alias)[0] == canonical, alias


def test_real_asr_pipeline_passes_hints_and_preserves_original_text():
    received = {}

    class Model:
        def transcribe(self, samples, **kwargs):
            received.update(kwargs)
            return iter([SimpleNamespace(text='Что такое чмот и човно?', no_speech_prob=0.01)]), None

    engine = SpeechEngine('unused')
    engine.model = Model()
    result = engine.transcribe(np.ones(6000, np.float32) * .1)
    assert result['text'] == 'Что такое chmod и chown?'
    assert result['raw_text'] == 'Что такое чмот и човно?'
    assert {item['to'] for item in result['corrections']} == {'chmod', 'chown'}
    assert received['hotwords'] == AQA_HOTWORDS
    assert received['condition_on_previous_text'] is False


def test_technical_hints_do_not_turn_silence_into_commands():
    engine = SpeechEngine('unused')
    result = engine.transcribe(np.zeros(16000, np.float32))
    assert result['text'] == ''


def test_corrected_question_is_published_and_sent_to_llm(tmp_path):
    from copilot.service import create_app
    runtime = create_app(tmp_path, 'test-secret').state.runtime
    runtime.settings.asr_device = 'cpu'
    published, received = [], []
    runtime.publish = published.append

    async def stream(question, session_id, **kwargs):
        received.append(question)
        yield {'type': 'done'}

    runtime.chat.stream = stream
    text, changes = normalize_technical_terms('Что такое чмот и човно?')
    try:
        asyncio.run(runtime.auto_answer({'source': 'loopback', 'text': text,
                                        'raw_text': 'Что такое чмот и човно?', 'corrections': changes}, 0))
        assert received == ['Что такое chmod и chown?']
        assert published[0]['type'] == 'transcript'
        assert published[0]['raw_text'] == 'Что такое чмот и човно?'
        assert published[0]['text'] == received[0]
    finally:
        runtime.store.close()
