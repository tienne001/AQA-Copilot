"""ASR vocabulary for QA, Linux and the supplied platform stack.

Decoder hints improve recognition; explicit whole-term aliases repair known
Russian transcriptions afterwards. Never use fuzzy matching on arbitrary words.
This module has no model, filesystem or network dependency.
"""
import re

# Keep this compact: faster-whisper truncates long hotword prompts. The complete
# list below is 220 tokens with the bundled multilingual Whisper tokenizer
# (below faster-whisper's 223-token hotword limit for this model).
# Linux commands come first so they survive even with a smaller prompt budget.
AQA_HOTWORDS = (
    'chmod, chown, chgrp, umask, sudo, grep, tail, journalctl, systemctl, '
    'PostgreSQL, RabbitMQ, Kafka, Python, C#, C++, Spring, Kotlin, Java, Groovy, '
    'TypeScript, JavaScript, npm, Node.js, Ant, Redux, Jira, TestRail, Jenkins, '
    'Confluence, Bitbucket, Figma, Slack, Docker, Kubernetes, K8s, VMware, '
    'VirtualBox, Git, Linux, Bash, SQL, OSI, TCP/IP, HTTP, HTTPS, REST, API, '
    'stack trace, on-premise, QA, AQA, Playwright, CI/CD, consumer group, '
    'offset, GET, POST, PUT, PATCH, DELETE, JSON, DNS, UDP, TLS, SSH, '
    'SELECT, JOIN, GROUP BY, HAVING, EXPLAIN, ACID, smoke, regression'
)

# Add aliases here, longest phrases before shorter aliases are matched
# automatically. English canonical spellings are also accepted case-insensitively.
VOCABULARY = (
    ('Allure', ('аллюр', 'аллюре', 'алюр', 'аллюра')),
    ('Page Object Model', ('пейдж обджект модел', 'пейдж обжект модел', 'пейдж объект модел')),
    ('POM', ('пи оу эм', 'пи о эм')),
    ('pytest', ('пай тест', 'пайтест', 'пай тесте', 'пайтесте')),
    ('Selenium', ('селениум', 'селениуме', 'селениума')),
    ('Cypress', ('сайпресс', 'сайпрес', 'сайпрессе')),
    ('JUnit', ('джей юнит', 'джейюнит')),
    ('NUnit', ('эн юнит', 'энюнит')),
    ('TestNG', ('тест эн джи', 'тестэнджи')),
    ('Cucumber', ('кукумбер', 'кукамбер')),
    ('chmod', ('чмод', 'чмодд', 'ч мод', 'си эйч мод', 'эйч мод', 'h-mod')),
    ('chown', ('чоун', 'чоунь', 'чоунэ', 'човн', 'човно', 'човну', 'ч оун', 'ч овн', 'эйч оун', 'h-own')),
    ('chgrp', ('чгруп', 'чгроп', 'чгрупп')),
    ('umask', ('юмаск', 'ю маск', 'умаск')),
    ('sudo', ('судо',)),
    ('grep', ('греп', 'грэп')),
    ('tail', ('тейл', 'тэйл')),
    ('journalctl', ('журнал си ти эл', 'джорнал си ти эл', 'джорналктл', 'журнал ctl', 'журналctl')),
    ('systemctl', ('систем си ти эл', 'системктл', 'систем ctl', 'системctl')),
    ('PostgreSQL', ('postgres', 'постгрес', 'постгресс', 'постгреса', 'постгресе', 'постгрескуэль', 'постгрес кью эл', 'постгре эс кью эл', 'постгре sql')),
    ('RabbitMQ', ('rabbit mq', 'рэббит эм кью', 'рэбит эм кью', 'раббит эм кью', 'рабит эм кью', 'рэббит', 'рэбит', 'раббит', 'рабит', 'рэббитмкью')),
    ('Kafka', ('кафка', 'кафке', 'кафки', 'кафку', 'кафкой')),
    ('Python', ('пайтон',)),
    ('C#', ('c sharp', 'си шарп', 'си шарпа', 'сишарп', 'си шарпе')),
    ('C++', ('c plus plus', 'си плюс плюс', 'си плас плас', 'сиплюсплюс')),
    ('Spring', ('спринг', 'спринга', 'спринге')),
    ('Spring Boot', ('спринг бут', 'spring бут', 'спрингбут')),
    ('Kotlin', ('котлин', 'котлина', 'котлине')),
    ('Java', ('джава', 'джаве', 'джавы', 'ява')),
    ('Groovy', ('груви',)),
    ('TypeScript', ('type script', 'тайпскрипт', 'тайп скрипт', 'тайпскрипте', 'тайпскрипта')),
    ('JavaScript', ('java script', 'джава скрипт', 'джаваскрипт', 'джаваскрипте', 'джаваскрипта', 'джава скрипте', 'джава скрипта', 'яваскрипт', 'джей эс', 'js')),
    ('npm', ('эн пи эм', 'н п м', 'энпием')),
    ('Node.js', ('node js', 'nodejs', 'ноуд джей эс', 'нод джей эс', 'ноуд')),
    ('Ant', ('апач ант', 'apache ant', 'ант')),
    ('Redux', ('редакс', 'редукс', 'редакса', 'редаксе')),
    ('Jira', ('джира', 'джире', 'джиру', 'джиры')),
    ('TestRail', ('test rail', 'тест рейл', 'тестрейл', 'тестрэйл', 'тест рейле', 'тестрейле')),
    ('Jenkins', ('дженкинс', 'дженкинса', 'дженкинсе')),
    ('Confluence', ('конфлюенс', 'конфлюэнс', 'конфлюенсе', 'конфлюэнсе', 'конфлуенс')),
    ('Bitbucket', ('bit bucket', 'битбакет', 'битбакете', 'бит бакет')),
    ('Figma', ('фигма', 'фигме', 'фигму')),
    ('Slack', ('слэк', 'слак', 'слаке', 'слэке')),
    ('Docker', ('докер', 'докера', 'докере', 'докером')),
    ('Docker Compose', ('docker компоуз', 'докер компоуз', 'докер композ', 'докеркомпоуз', 'docker, compose')),
    ('Dockerfile', ('докер файл', 'докерфайл', 'docker file')),
    ('Kubernetes', ('кубернетес', 'кубернетис', 'кубернетс', 'кубернетесе', 'кубернетисе', 'кубер', 'кубере', 'кубера', 'k8s', 'кей эйт эс', 'к восемь эс')),
    ('kubectl', ('кубектл', 'куб контрол', 'кьюб контрол', 'куб си ти эл')),
    ('VMware', ('vm ware', 'ви эм вэр', 'ви эм варе', 'виэмваре', 'вмваре', 'вмварь')),
    ('VirtualBox', ('virtual box', 'виртуал бокс', 'виртуалбокс', 'виртуалбоксе')),
    ('Git', ('гит', 'гита', 'гите', 'гитом')),
    ('GitLab', ('git lab', 'гитлаб', 'гитлабe', 'гитлабе')),
    ('Linux', ('линукс', 'линукса', 'линуксе', 'линуксом')),
    ('Bash', ('баш', 'бэш')),
    ('SQL', ('эс кью эл', 'эс кью эль', 'эс ку эл', 'эскьюэль', 'сиквел')),
    ('OSI', ('о эс ай', 'оу эс ай')),
    ('модель OSI', ('модель оси',)),
    ('TCP/IP', ('tcp ip', 'tcpip', 'ти си пи ай пи', 'тэ цэ пэ ай пи')),
    ('TCP', ('ти си пи', 'тэ цэ пэ')),
    ('UDP', ('ю ди пи', 'у дэ пэ')),
    ('HTTP', ('эйч ти ти пи', 'аш ти ти пи')),
    ('HTTPS', ('эйч ти ти пи эс', 'аш ти ти пи эс')),
    ('DNS', ('ди эн эс', 'дэ эн эс')),
    ('TLS', ('ти эл эс', 'тэ эл эс')),
    ('SSH', ('эс эс эйч', 'эс эс аш')),
    ('REST', ('рест', 'рэст')),
    ('API', ('апи', 'эй пи ай')),
    ('JSON', ('джей сон', 'джисон')),
    ('XML', ('икс эм эл', 'икс эм эль')),
    ('gRPC', ('джи ар пи си', 'джи эр пи си')),
    ('WebSocket', ('web socket', 'веб сокет', 'вебсокет', 'вебсокеты')),
    ('stack trace', ('stacktrace', 'стек трейс', 'стэк трейс', 'стектрейс', 'стек трейсом', 'стектрейсу', 'стек трейсу')),
    ('NullPointerException', ('нул поинтер эксепшен', 'нал поинтер эксепшн', 'нуллпоинтерэксепшен')),
    ('on-premise', ('on premise', 'on premises', 'он премис', 'он прем', 'онпрем', 'онпремис', 'он премайз', 'онпремайз')),
    ('QA', ('кью эй', 'ку эй')),
    ('AQA', ('эй кью эй', 'а кью эй', 'акуа')),
    ('Playwright', ('плейрайт', 'плейврайт', 'плей райт', 'плейрайте')),
    ('CI/CD', ('ci cd', 'си ай си ди', 'сиайсиди')),
    ('consumer group', ('консьюмер групп', 'консюмер групп', 'консьюмер группа', 'консюмер группа')),
    ('consumer', ('консьюмер', 'консюмер')),
    ('offset', ('оффсет', 'офсет', 'оффсеты', 'офсеты')),
    ('dead letter queue', ('дед леттер кью', 'дед летер кью')),
    ('exchange', ('эксчендж', 'эксчейндж')),
    ('routing key', ('роутинг кей', 'роутинг ки')),
    ('SELECT', ('селект', 'сэлект')),
    ('JOIN', ('джоин', 'джойн')),
    ('LEFT JOIN', ('left джоин', 'left джойн', 'лефт джоин', 'лефт джойн')),
    ('INNER JOIN', ('иннер джоин', 'иннер джойн')),
    ('GROUP BY', ('груп бай', 'групп бай')),
    ('ORDER BY', ('ордер бай',)),
    ('HAVING', ('хэвинг', 'хевинг')),
    ('EXPLAIN', ('эксплейн',)),
    ('ACID', ('эй сид', 'эсид', 'асид')),
    ('COMMIT', ('коммит', 'комит')),
    ('ROLLBACK', ('роллбэк', 'ролбэк', 'роллбек')),
    ('smoke', ('смоук', 'смок тест')),
    ('sanity', ('санити',)),
    ('flaky', ('флейки', 'флэйки')),
    ('test case', ('тест кейс', 'тесткейс')),
    ('test cases', ('тест кейсы', 'тесткейсы', 'тест кейсов', 'тесткейсов')),
    ('checklist', ('чек лист', 'чеклист')),
    ('black box', ('блэк бокс',)),
    ('white box', ('вайт бокс',)),
    ('end-to-end', ('end to end', 'энд ту энд', 'е ту е', 'и ту и')),
    ('boundary value analysis', ('баундари вэлью анализ',)),
    ('partition', ('партишен', 'партишн')),
)


def _phrase(value):
    return re.escape(value).replace(r'\ ', r'[\s-]+')


_CANONICAL = {alias.casefold(): canonical for canonical, aliases in VOCABULARY
              for alias in (canonical, *aliases)}
def _terms_pattern(aliases):
    return re.compile(
        r'(?<![\w./\\])(?:' + '|'.join(_phrase(alias) for alias in sorted(aliases, key=len, reverse=True)) +
        r')(?![\w/\\]|://|\.\w)', re.IGNORECASE)


_ALIASES = _terms_pattern(_CANONICAL)
_PROTECTED = re.compile(r'`[^`]*`|\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>"«»]+|'
                        r'\b[A-Za-z]:[\\/][^\s<>"«»]+|(?<!\w)/[^\s<>"«»]+')
_LINUX_CONTEXT = re.compile(
    r'chmod|chown|linux|линукс|команд|прав[аоы]|доступ|файл|каталог|владел|'
    r'\b(?:755|644|777|rwx)\b', re.IGNORECASE)
_CONTEXTUAL = (
    ('chmod', ('чмот',), _LINUX_CONTEXT, None),
    ('Python', ('питон', 'питона', 'питоне', 'питоном'),
     re.compile(r'язык|код|скрипт|программ|автоматиз|тест|библиотек|python|java|запуск|разработ|c#|c\+\+', re.I),
     re.compile(r'зоопарк|зме[яию]|животн|террариум|пресмыка', re.I)),
    ('Node.js', ('нода', 'ноде'),
     re.compile(r'npm|typescript|javascript|redux|frontend|фронтенд|node\.?js|тайпскрипт|джаваскрипт', re.I),
     re.compile(r'kubernetes|кубер|кластер|узел|worker|мастер|\bpod\b|notready|control plane', re.I)),
    ('JSON', ('джейсон',),
     re.compile(r'формат|валид|сериал|объект|данн|схем|ответ|request|response|api|xml|yaml|payload|парс', re.I),
     re.compile(r'попросил|сказал|приш[её]л|человек|сотрудник|разработчик|зовут', re.I)),
    ('producer', ('продьюсер', 'продюсер'),
     re.compile(r'kafka|rabbitmq|topic|очеред|сообщен|брокер|топик|consumer|консьюмер|событ', re.I),
     re.compile(r'фильм|кино|акт[её]р|музык', re.I)),
    ('Jira', ('Jiri', 'Jire', 'Джири'),
     re.compile(r'задач|баг|тикет|трекер|issue', re.I),
     re.compile(r'попросил|сказал|приш[её]л|человек|сотрудник|зовут', re.I)),
)


def normalize_technical_terms(text):
    """Return corrected text and an audit trail. Do not change unrelated words."""
    corrections = []

    def replace(match):
        original = match.group(0)
        key = re.sub(r'[\s-]+', ' ', original.casefold())
        # Canonical spellings containing a hyphen must retain their exact key.
        canonical = _CANONICAL.get(original.casefold(), _CANONICAL.get(key, original))
        if canonical != original:
            corrections.append({'from': original, 'to': canonical})
        return canonical

    # Leave URLs (including query parameters), paths and code untouched.
    protected, cursor, chunks = [], 0, []
    for match in _PROTECTED.finditer(text):
        chunks.append(_ALIASES.sub(replace, text[cursor:match.start()]))
        protected.append((len(chunks), match.group(0)))
        chunks.append(match.group(0))
        cursor = match.end()
    chunks.append(_ALIASES.sub(replace, text[cursor:]))
    protected_indexes = {index for index, _ in protected}
    context = ' '.join(chunk for index, chunk in enumerate(chunks) if index not in protected_indexes)
    for canonical, aliases, required, forbidden in _CONTEXTUAL:
        if not required.search(context) or (forbidden and forbidden.search(context)):
            continue
        def replace_contextual(match, canonical=canonical):
            corrections.append({'from': match.group(0), 'to': canonical})
            return canonical
        pattern = _terms_pattern(aliases)
        chunks = [chunk if index in protected_indexes else pattern.sub(replace_contextual, chunk)
                  for index, chunk in enumerate(chunks)]
    return ''.join(chunks), corrections
