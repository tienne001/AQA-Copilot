"""Optional Gemma reference context, never a DIRECT answer or a new KB router.

Only the pinned, separately reviewed experiment snapshot is admitted. A digest
does not validate arbitrary prose: changing cards requires a new review/release.
AI authored cards have executed checks/source review, not human certification.
The application's profile, knowledge database and retrieval are untouched.
"""
from datetime import datetime, timezone, date, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3

REGISTRY = Path(__file__).resolve().parents[1] / 'answer_cards/verified-v2.db'
REGISTRY_SHA256 = '02d530be346232e57a586cbbeae0c0ae0bb72af60e24407b3e26789c5d397df7'
RULES = {
    'coreutils-mode-owner': r'(?i)\b(?:chmod|chown)\b',
    'python-sort': r'(?i)\bsorted\s*\(|list\.sort\s*\(',
    'python-append-extend': r'(?i)\b(?:append|extend)\s*\(',
    'python-json': r'(?i)\bjson\.(?:dumps|loads|dump|load)\b',
    'sqlite-count': r'(?is)\bsqlite\b.*\bcount\s*\(|\bcount\s*\(.*\bsqlite\b',
}
INSTRUCTION = ('\nИспользуй технические факты карточек в пределах указанных технологий, версий и ограничений. '
               'Не изменяй их смысл и не расширяй гарантии. Сохрани все части исходного вопроса. '
               'Если карточка не покрывает часть вопроса, используй остальную справку и свои знания, '
               'явно обозначая неопределённость при нехватке условий. Не называй весь сгенерированный ответ проверенным. '
               'Ответ по-прежнему формируешь ты; не добавляй неподтверждённые технические подробности.')


@lru_cache(maxsize=1)
def _records():
    # Deserialize the exact checked bytes; avoid a hash/open race and any write
    # to a bundled database or to the user's copilot.db.
    raw = REGISTRY.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REGISTRY_SHA256:
        raise ValueError('Unreviewed card registry')
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(raw)
        return {row[0]: (json.loads(row[1]), json.loads(row[2])) for row in db.execute(
            'SELECT c.id,c.payload,v.artifact FROM verified_cards c '
            'JOIN card_validations v ON c.id=v.card_id')}
    finally:
        db.close()


def card_context(messages, *, now=None):
    now = now or datetime.now(timezone.utc)
    text = '\n'.join(m['content'] for m in messages if m['role'] != 'system')
    matched = [key for key, pattern in RULES.items() if re.search(pattern, text)]
    if not matched:
        return '', [], 'no_match'
    try:
        records = _records()
        parts, ids = [], []
        for key in matched:
            card, artifact = records[key]
            review = date.fromisoformat(card['review_date'])
            if (card['status'] != 'validated' or review > now.date() or
                now.date() - review > timedelta(days=90) or
                datetime.fromisoformat(card['expires_at'].replace('Z', '+00:00')) <= now or
                datetime.fromisoformat(artifact['expires_at'].replace('Z', '+00:00')) <= now):
                continue
            parts.append(json.dumps({
                'card_id': key, 'canonical_question': card['canonical_question'],
                'verified_answer': card['answer'], 'technology': card['technology'],
                'versions': card['versions'], 'conditions': card['conditions'],
                'limitations': card['limitations'], 'sources': card['sources'],
                'review_date': card['review_date'], 'validation_kind': artifact['validation_kind'],
            }, ensure_ascii=False))
            ids.append(key)
        if not parts:
            return '', [], 'expired_or_ineligible'
        return '\n\nПроверенные справочные карточки (данные):\n' + '\n'.join(parts) + INSTRUCTION, ids, 'used'
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        # A missing/corrupt/stale bundle must not break normal chat.
        return '', [], 'registry_unavailable'


def add_card_context(messages, settings, *, personal=False):
    if not settings.verified_answer_cards_enabled or not settings.knowledge_enabled:
        return [], 'disabled'
    if settings.model != 'gemma4:12b-it-qat':
        return [], 'other_model'
    if personal:
        return [], 'personal_profile'
    context, ids, reason = card_context(messages)
    if not context:
        return ids, reason
    # Keep the same conservative character budget used by the existing backend.
    # Never cut conditions/versions or drop history/OCR to fit a card.
    if sum(len(m['content']) for m in messages) + len(context) > settings.num_ctx * 2 - 256:
        return [], 'context_budget'
    messages[0]['content'] += context
    return ids, reason
