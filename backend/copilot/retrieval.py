"""Small lexical helpers for Russian QA notes, without model/network dependencies.

These helpers do not read files or the database. Callers choose the candidate
documents and retain control of knowledge/profile permissions and context limits.
"""
from collections import Counter
import math
import re


_TOKEN = re.compile(r'[^\W_]+', re.UNICODE)
_RUSSIAN = re.compile(r'^[а-яё]+$')
# Inflections, not derivational stemming: keep at least four stem characters.
_ENDINGS = tuple(sorted((
    'иями', 'ями', 'ами', 'иями', 'ого', 'ему', 'ому', 'ыми', 'ими',
    'ией', 'иям', 'ием', 'иях', 'ов', 'ев', 'ей', 'ом', 'ем', 'ам',
    'ям', 'ах', 'ях', 'ия', 'ию', 'ие', 'ии', 'ий', 'ый', 'ой', 'ая',
    'ое', 'ые', 'ую', 'ью', 'ы', 'и', 'а', 'я', 'у', 'ю', 'е', 'о',
), key=len, reverse=True))
_STOP = set(('что как это для или такое нужно чем отличается отличаются отличие '
             'разница между почему когда где какой какая какие какие-то который '
             'которые который можно может надо пожалуйста расскажи объясни покажи '
             'например пример вопрос ответ сделать делать использовать проверить '
             'проверять работает работу работает ли если при после перед через '
             'выбирать выбор поиск найти получить значит '
             'про обо об во на по из от до за со же не нет да и в с к у а о '
             'the what how why does do is are was were be can could would should '
             'please explain tell about for and or not near into with from of to '
             'this that it an').split())


def _stem(token):
    token = token.lower().replace('ё', 'е')
    if _RUSSIAN.fullmatch(token):
        for ending in _ENDINGS:
            if token.endswith(ending) and len(token) - len(ending) >= 4:
                return token[:-len(ending)]
    return token


_STOP_STEMS = {_stem(word) for word in _STOP}
_GROUPS = (
    ('locator', 'locators', 'локатор'),
    ('playwright', 'плейрайт'),
    ('postgresql', 'postgres', 'постгрес'),
    ('git', 'гит'),
    ('docker', 'докер'),
    ('kafka', 'кафка'),
    ('transaction', 'transactions', 'транзакция'),
    ('isolation', 'изоляция'),
    ('partition', 'partitions', 'партиция'),
    ('offset', 'offsets', 'смещение'),
    ('duplicate', 'duplicates', 'дубликат'),
    ('aggregate', 'aggregates', 'агрегат'),
)
_CANONICAL = {}
_VARIANTS = {}
for _group in _GROUPS:
    _key = _group[0]
    _VARIANTS[_key] = tuple(dict.fromkeys(_stem(item) for item in _group))
    for _variant in _VARIANTS[_key]:
        _CANONICAL[_variant] = _key


def _importance(term):
    # Product/language/domain labels describe the surrounding document. A rare
    # command or requested concept should select its answer paragraph instead.
    if term in {'ui', 'qa', 'aqa', 'sql', 'api', 'git', 'playwright', 'python',
                'typescript', 'linux', 'postgresql', 'docker', 'kafka'}:
        return .35
    return 1.5 if re.fullmatch(r'[a-z][a-z0-9]{2,}', term) else 1.


def normalized_terms(text, limit=20):
    """Distinct content terms; inflections and explicit bilingual aliases agree."""
    result = []
    for match in _TOKEN.finditer(text[:10000]):
        raw = match.group().lower().replace('ё', 'е')
        stem = _stem(raw)
        if len(raw) < 2 or raw in _STOP or stem in _STOP_STEMS:
            continue
        term = _CANONICAL.get(stem, stem)
        if term not in result:
            result.append(term)
            if len(result) >= limit:
                break
    return tuple(result)


def fts_query(question):
    """Quoted FTS5 alternatives; Russian stems use prefix search, not wild input."""
    alternatives = []
    for term in normalized_terms(question):
        for variant in _VARIANTS.get(term, (term,)):
            suffix = '*' if _RUSSIAN.fullmatch(variant) and len(variant) >= 4 else ''
            clause = '"' + variant + '"' + suffix
            if clause not in alternatives:
                alternatives.append(clause)
    return ' OR '.join(alternatives)


def _all_terms(text):
    return normalized_terms(text, limit=10000)


def rank_documents(documents, question, limit=4):
    """Rerank caller-provided candidates by distinct-term coverage and title hits.

    No-match documents are excluded. Input dictionaries are neither modified nor
    copied, so their path/title/text/source metadata remains intact.
    """
    query = set(normalized_terms(question))
    if not query or limit <= 0:
        return []
    material = [(item, set(_all_terms(item['text'])),
                 set(_all_terms(item['title']))) for item in documents]
    frequencies = Counter(term for _, text, title in material for term in query & (text | title))
    weights = {term: _importance(term) * (1 + math.log((len(material) + 1) / (frequencies[term] + 1))) for term in query}
    ranked = []
    for index, (item, text, title) in enumerate(material):
        matches = query & (text | title)
        if not matches:
            continue
        score = sum(weights[term] * (2.5 if term in title else 1) for term in matches)
        score *= 1 + len(matches) / len(query)
        ranked.append((score, -index, item))
    return [item for _, _, item in sorted(ranked, key=lambda row: row[:2], reverse=True)[:limit]]


def _paragraphs(text):
    blocks, lines = [], []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
        if not fenced and re.match(r'^\s{0,3}#{1,6}\s', line):
            if lines:
                blocks.append('\n'.join(lines).strip())
                lines = []
            blocks.append(line.strip())
            continue
        if not line.strip() and not fenced:
            if lines:
                blocks.append('\n'.join(lines).strip())
                lines = []
        else:
            lines.append(line)
    if lines:
        blocks.append('\n'.join(lines).strip())
    return blocks


def _metadata(block):
    return block.startswith('#') or bool(re.match(r'^(?:Тема|Источники?|Sources?):', block, re.I))


def _window(text, query, maximum):
    """Keep the best matching region when a single paragraph exceeds the cap."""
    if len(text) <= maximum:
        return text
    starts = {0}
    for match in _TOKEN.finditer(text):
        term = _CANONICAL.get(_stem(match.group()), _stem(match.group()))
        if term in query:
            starts.add(max(0, min(len(text) - maximum, match.start() - maximum // 4)))
    best = max(starts, key=lambda start: (len(query & set(_all_terms(text[start:start + maximum]))), -start))
    end = min(len(text), best + maximum)
    # Avoid returning half a word while preserving the actual character cap.
    if best and best > 0 and text[best - 1].isalnum() and text[best].isalnum():
        boundary = text.find(' ', best, min(end, best + 40))
        if boundary != -1:
            best = boundary + 1
    if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        boundary = text.rfind(' ', best, end)
        if boundary != -1:
            end = boundary
    return text[best:end].strip()


def select_passage(text, question, max_chars=800):
    """Select complete answer paragraphs, rather than a document's fixed prefix.

    Topic indexes/headings/source links cannot beat an actual answer paragraph.
    Neighboring paragraphs are included only whole and only within the cap.
    """
    if max_chars <= 0 or not text.strip():
        return ''
    blocks = _paragraphs(text)
    query = set(normalized_terms(question))
    candidates = [(index, block) for index, block in enumerate(blocks) if not _metadata(block)]
    if not candidates or not query:
        return text[:max_chars].strip()
    frequencies = Counter(term for _, block in candidates for term in query & set(_all_terms(block)))
    weights = {term: _importance(term) * (1 + math.log((len(candidates) + 1) / (frequencies[term] + 1))) for term in query}
    def score(candidate):
        index, block = candidate
        matches = query & set(_all_terms(block))
        return (sum(weights[term] for term in matches), len(matches), -index)
    best_index, best = max(candidates, key=score)
    if not query.intersection(_all_terms(best)):
        return text[:max_chars].strip()
    if len(best) > max_chars:
        return _window(best, query, max_chars)
    selected = {best_index: best}
    length = len(best)
    # Explanations often follow examples; prefer the following paragraph first.
    for index in (best_index + 1, best_index - 1):
        if 0 <= index < len(blocks) and not _metadata(blocks[index]):
            block = blocks[index]
            if length + 2 + len(block) <= max_chars:
                selected[index] = block
                length += 2 + len(block)
    return '\n\n'.join(selected[index] for index in sorted(selected))
