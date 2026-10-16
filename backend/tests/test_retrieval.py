import sqlite3

from copilot.retrieval import fts_query, normalized_terms, rank_documents, select_passage


def test_russian_inflections_and_bilingual_locators_share_content_terms():
    assert normalized_terms('Расскажи, пожалуйста, про локаторы') == ('locator',)
    assert normalized_terms('локаторами locators Locator') == ('locator',)
    assert normalized_terms('транзакциями транзакция транзакции transactions') == ('transaction',)
    assert normalized_terms('изоляция изоляции') == ('isolation',)


def test_fts_expands_inflections_and_does_not_accept_query_operators():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE VIRTUAL TABLE notes USING fts5(text)')
    db.executemany('INSERT INTO notes VALUES (?)', [('Locator finds the element.',), ('Работа с локаторами.',), ('Git branches and commits.',)])
    rows = db.execute('SELECT text FROM notes WHERE notes MATCH ?', (fts_query('Объясни локаторы'),)).fetchall()
    assert len(rows) == 2
    assert fts_query('" OR * NEAR(') == ''
    db.close()


def test_technical_term_ranks_playwright_above_generic_git_qa_prose():
    documents = [
        {'title': 'Git для QA', 'path': 'git', 'text': 'Чтобы проверить приложение, нужно сделать проверку после изменения.'},
        {'title': 'Playwright UI: locators', 'path': 'ui', 'text': 'Locator resolves an element again before every action.'},
    ]
    assert [item['path'] for item in rank_documents(documents, 'Как проверить локаторы?')] == ['ui']
    assert documents[0]['path'] == 'git'


def test_relevant_complete_postgresql_paragraph_after_long_intro_is_kept():
    answer = ('В PostgreSQL Read Committed — уровень по умолчанию: SELECT видит снимок '
              'подтверждённых данных на начало команды. Два SELECT могут увидеть разные '
              'подтверждённые изменения. Read Uncommitted в PostgreSQL ведёт себя как Read Committed.')
    text = '# SQL\n\nТема: PostgreSQL, Read Uncommitted.\n\n' + ('Введение в ACID и бизнес-правила. ' * 40) + '\n\n' + answer + '\n\nИсточник: https://example.test/read-uncommitted'
    passage = select_passage(text, 'Как работает READ UNCOMMITTED в PostgreSQL?', 800)
    assert answer in passage
    assert 'Источн' not in passage
    assert len(passage) <= 800


def test_count_null_and_join_answer_is_not_cut_at_a_fixed_document_prefix():
    answer = ('NULL проверяется через IS NULL. COUNT(*) считает строки, COUNT(column) '
              'считает ненулевые значения. JOIN один ко многим может исказить SUM.')
    text = '# SQL JOIN\n\n' + ('Сначала определить источники данных. ' * 40) + '\n\n' + answer
    assert answer in select_passage(text, 'Чем COUNT(column) отличается от COUNT(*) при NULL и JOIN?', 800)


def test_code_block_and_following_assumption_stay_whole_when_they_fit():
    text = '# SQL\n\n```sql\nSELECT COUNT(o.id)\n\nFROM users u LEFT JOIN orders o ON o.user_id=u.id;\n```\n\norders.id предполагается ненулевым.'
    passage = select_passage(text, 'LEFT JOIN COUNT', 400)
    assert '```sql' in passage and passage.count('```') == 2
    assert 'orders.id предполагается ненулевым.' in passage


def test_long_single_paragraph_selects_the_matching_end_and_respects_cap():
    text = 'Общее введение. ' * 100 + 'chmod меняет права доступа, chown меняет владельца файла.'
    passage = select_passage(text, 'chmod chown', 150)
    assert 'chmod меняет права' in passage
    assert 'chown меняет владельца' in passage
    assert len(passage) <= 150
    assert select_passage(text, 'chmod', 0) == ''


def test_heading_without_blank_line_does_not_hide_answer_paragraph():
    text = '# Транзакции\nRead Uncommitted в PostgreSQL ведёт себя как Read Committed.\n\nИное введение.'
    assert 'Read Uncommitted в PostgreSQL ведёт себя как Read Committed.' in select_passage(text, 'READ UNCOMMITTED', 200)


def test_domain_label_does_not_outweigh_requested_locator_answer():
    definition = 'Locator заново находит элемент перед действием. Выбирать роль и accessible name.'
    text = '# Playwright UI\n\n' + definition + '\n\n' + ('Общее введение. ' * 80) + '\n\nUI может ломаться из-за анимации.'
    assert definition in select_passage(text, 'Как выбирать локаторы в UI?', 180)


def test_command_answer_outweighs_generic_goal_of_searching_regression():
    definition = 'Регрессия возникает после изменения. Для поиска причины нужен повторяемый сценарий.'
    procedure = 'Git bisect выбирает промежуточную ревизию. Проверить её и отметить good либо bad.'
    text = '# Git\n\n' + definition + '\n\n' + ('Прочее введение. ' * 80) + '\n\n' + procedure
    assert procedure in select_passage(text, 'Как работает git bisect для поиска регрессии?', 180)
