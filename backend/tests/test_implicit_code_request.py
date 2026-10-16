import pytest
from copilot.code_request import code_request_instruction,CODE_FIRST

@pytest.mark.parametrize('question',[
    'Смотри, нужно сделать алгоритм, который перебирает одномерный массив из 10 случайных чисел и в нем убирает каждое третье число, которое больше 5.',
    'Нужно создать алгоритм обработки массива: убрать отрицательные числа.',
    'Дан массив чисел. Удалить дубликаты, сохранив порядок.',
    'Есть массив целых чисел, нужно найти максимум.',
    'Как убрать дубликаты из массива?',
    'Найди первый повторяющийся элемент в массиве.',
    'Преобразуй массив объектов в словарь по id.',
    'Дана строка. Нужно развернуть порядок слов.',
    'Нужно реализовать проверку строки на палиндром.',
    'Как посчитать число повторений каждого значения в списке?',
    'Нужно сделать функцию, которая возвращает сумму чисел.',
])
def test_implicit_programming_tasks_need_implementation(question):
    assert code_request_instruction(question)==CODE_FIRST

@pytest.mark.parametrize('question',[
    'Что такое алгоритм?',
    'Как работает сортировка массива?',
    'Объясни, почему удаление элементов массива при обходе опасно.',
    'Расскажи про сложность поиска в массиве.',
    'Опиши алгоритм тестирования формы авторизации.',
    'Нужен алгоритм проверки формы авторизации.',
    'Напиши алгоритм тестирования формы авторизации.',
    'Дан массив. Нужно удалить дубликаты, но только словами, без кода.',
    'Нужно сделать алгоритм обработки массива, не пиши код.',
    'Напиши план тестирования формы авторизации.',
    'Нужно удалить старые строки из тест-плана.',
])
def test_explanations_and_qa_plans_remain_prose(question):
    assert not code_request_instruction(question)

@pytest.mark.parametrize('question',[
    'Покажи пример','Как это будет выглядеть?', 'А можешь это написать?',
    'Реализуй решение','Сделай алгоритм','Давай рабочий пример','Теперь на Python',
])
def test_followups_use_previous_algorithm_task(question):
    history=[{'role':'user','content':'Дан массив строк, нужно удалить повторы, сохранив порядок.'},
             {'role':'assistant','content':'Можно собрать уникальные элементы в исходном порядке.'}]
    assert code_request_instruction(question,history)==CODE_FIRST

@pytest.mark.parametrize('question',['Мне нужен код','Хочу рабочий скрипт','Мне нужна реализация'])
def test_request_for_code_without_an_imperative(question):
    assert code_request_instruction(question)==CODE_FIRST

@pytest.mark.parametrize('question',['Мне не нужен код','Не хочу код','Хочу объяснение без кода'])
def test_negative_desires_are_not_code_requests(question):
    assert not code_request_instruction(question)
