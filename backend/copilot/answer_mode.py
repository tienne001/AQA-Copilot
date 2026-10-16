"""Conservative routing by question form, without topic-specific answers."""
import re

_SIMPLE = re.compile(
    r'^(?:что\s+такое|что\s+значит|как\s+расшифровывается|'
    r'какими\s+|с\s+какими\s+|какие\s+(?:языки|инструменты|фреймворки|технологии)\b)', re.I)
_CONDITIONS = re.compile(
    r'\b(?:всегда|никогда|обязательно|обязан\w*|гарант\w*|невозможно|если|почему|'
    r'не|без|но|при|нельзя|можно)\b', re.I)
_EXPERIENCE = re.compile(
    r'резюме|\bопыт\w*|\b(?:ты|твой|твоя|твои|твоем|твоём|тебя|тебе|вы|ваш\w*|ваша|ваши)\b|'
    r'пользовал\w*|работал\w*|использовал\w*|применял\w*|занимал\w*|внедрял\w*|'
    r'тестировал\w*|автоматизировал\w*|расскаж\w*\s+о\s+себе|'
    r'\b(?:использу(?:ешь|ете)|применя(?:ешь|ете)|работа(?:ешь|ете)|'
    r'пиш(?:ешь|ете)|зна(?:ешь|ете)|владе(?:ешь|ете)|'
    r'тестиру(?:ешь|ете)|автоматизиру(?:ешь|ете)|внедря(?:ешь|ете)|'
    r'разрабатыва(?:ешь|ете)|пользу(?:ешься|етесь)|занима(?:ешься|етесь))\b|'
    r'каким\w*.*фреймворк|^фреймворк\w*\s*\??$', re.I)


def needs_profile(question, has_technical_reference):
    """Keep pinned facts for experience and ambiguous questions, skip unrelated CV in technical explanations."""
    return bool(_EXPERIENCE.search(question)) or not has_technical_reference


def use_reasoning(question, settings):
    if not settings.reasoning_enabled:
        return False
    if not settings.adaptive_reasoning:
        return True
    value = question.strip()
    # Only short definitions or plain experience questions take the fast path.
    # Conditions, code, multiple parts and unknown forms retain reasoning.
    simple = (len(value) <= 140 and value.count('?') <= 1 and
              not re.search(r'[\d`;<>=\n]', value) and
              not _CONDITIONS.search(value) and _SIMPLE.search(value))
    return not bool(simple)
