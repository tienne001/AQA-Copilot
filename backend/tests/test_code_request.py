import pytest
from copilot.code_request import code_request_instruction,CODE_FIRST

@pytest.mark.parametrize('question',[
    'Напиши пожалуйста код','Напиши, пожалуйста, код.','Можешь написать код на JavaScript?',
    'Покажи код','Дай пример кода для запроса API','Сгенерируй скрипт на Python',
    'Реализуй функцию сортировки','Напишите автотест на Playwright',
    'Как написать SQL-запрос для подсчета строк?','Код, пожалуйста','Можно код, пожалуйста?',
    'Напиши функцию генерации тест-кейсов','Write code for this task','Show a JavaScript function',
])
def test_explicit_code_request(question):
    assert code_request_instruction(question)==CODE_FIRST

@pytest.mark.parametrize('question',[
    'Покажи пример','Напиши, пожалуйста','Как это написать?', 'Можешь показать пример?',
])
def test_contextual_followup(question):
    history=[{'role':'user','content':'Как дождаться ответа API в Playwright после клика?'},
             {'role':'assistant','content':'Создать ожидание до клика, затем дождаться ответа.'}]
    assert code_request_instruction(question,history)==CODE_FIRST

@pytest.mark.parametrize('question',[
    'Чем отличаются smoke и sanity?','Покажи пример','Как это написать?',
    'Не пиши код, объясни словами','Напиши объяснение без кода',
    'Код не пиши, напиши объяснение','Не нужно писать код',
    'Напиши код? Нет, только словами','Что значит фраза «напиши код»?',
    'Покажи пример фразы «напиши код»','Напиши тест-план','Напиши тест-кейс на авторизацию',
    'Напиши чек-лист','Explain without code',"Don't write code",
])
def test_no_false_code_override(question):
    assert not code_request_instruction(question)

def test_nontechnical_history_does_not_turn_examples_into_code():
    assert not code_request_instruction('Покажи пример',[{'role':'user','content':'Чем отличается smoke от sanity?'}])
