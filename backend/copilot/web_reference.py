"""Opt-in static official references; question text never becomes a network URL.

Importing this module and constructing a client perform no network I/O. Only an
explicit fetch_references call requests at most two fixed public documents.
"""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
import re
import time
from urllib.parse import urlsplit

import httpx

from .retrieval import select_passage


MAX_DOCUMENT_BYTES = 1024 * 1024
CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_CACHE_ENTRIES = 16


@dataclass(frozen=True)
class _Source:
    title: str
    url: str
    pattern: str
    scope: str = ''


_SOURCES = (
    _Source('PostgreSQL: transaction isolation', 'https://www.postgresql.org/docs/current/transaction-iso.html',
            r'read\s+(?:uncommitted|committed)|repeatable\s+read|serializable|изоляц|dirty\s+read|транзакц'),
    _Source('PostgreSQL: aggregate functions', 'https://www.postgresql.org/docs/current/functions-aggregate.html',
            r'\b(?:count|sum|avg|aggregate)\b|агрегат|\bnull\b'),
    _Source('PostgreSQL: table expressions and JOIN', 'https://www.postgresql.org/docs/current/queries-table-expressions.html',
            r'\b(?:left|right|inner|full|cross)\s+join\b|\bjoin\b.*\b(?:on|where)\b'),
    _Source('PostgreSQL: EXPLAIN', 'https://www.postgresql.org/docs/current/using-explain.html',
            r'\bexplain\b|seq\s+scan|index\s+scan|план\w*\s+запрос'),
    _Source('PostgreSQL: constraints', 'https://www.postgresql.org/docs/current/ddl-constraints.html',
            r'\b(?:constraint|unique)\b|primary\s+key|foreign\s+key|not\s+null|внешн\w*\s+ключ|ограничен\w*\s+целост'),
    _Source('Playwright: locators', 'https://playwright.dev/docs/locators',
            r'\blocators?\b|локатор|strictness|\bstrict\b|getby(?:role|testid|text|label)|xpath'),
    _Source('Playwright: actionability', 'https://playwright.dev/docs/actionability',
            r'\b(?:click|actionability|visible|force)\b|auto[- ]?wait|клик|автоожидан'),
    _Source('Playwright: assertions', 'https://playwright.dev/docs/test-assertions',
            r'\b(?:expect|assertions?|assert)\b|tohavetext|textcontent|провер\w*\s+текст'),
    _Source('Playwright: APIRequestContext', 'https://playwright.dev/docs/api/class-apirequestcontext',
            r'apirequestcontext|api\s*request|playwright.*\bapi\b|storage[_ ]?state'),
    _Source('Playwright: page object models', 'https://playwright.dev/docs/pom',
            r'\bpom\b|page\s*object|pageobject|объект\w*\s+страниц'),
    _Source('Playwright: browser context isolation', 'https://playwright.dev/docs/browser-contexts',
            r'browsercontext|browser\s*contexts?|изоляц.*(?:браузер|контекст)|(?:браузер|контекст).*изоляц'),
    _Source('Playwright: network', 'https://playwright.dev/docs/network',
            r'waitforresponse|waitforrequest|\broute\b|network|сеть|ответ.*клик',
            r'playwright|плейрайт|waitforresponse|waitforrequest|\broute\b|ответ.*клик'),
    _Source('Dockerfile reference', 'https://docs.docker.com/reference/dockerfile/',
            r'dockerfile|entrypoint|\bcmd\b|\bcopy\b.*\badd\b'),
    _Source('Docker Compose: volumes', 'https://docs.docker.com/reference/compose-file/volumes/',
            r'\bvolumes?\b|bind\s+mount|монтирован|\bтом(?:а|ов|ы)?\b', r'docker|докер|compose|volume|bind\s+mount'),
    _Source('Docker Compose: startup order', 'https://docs.docker.com/compose/how-tos/startup-order/',
            r'depends[_ ]on|service_healthy|healthcheck|поряд\w*\s+запуск'),
    _Source('Linux chmod(2)', 'https://man7.org/linux/man-pages/man2/chmod.2.html', r'\bchmod\b|\brwx\b'),
    _Source('Linux chown(2)', 'https://man7.org/linux/man-pages/man2/chown.2.html', r'\bchown\b'),
    _Source('Linux unlink(2)', 'https://man7.org/linux/man-pages/man2/unlink.2.html',
            r'\bunlink\b|удален\w*\s+открыт|открыт\w*\s+файл.*удал|\brm\b(?=.*(?:linux|log|open|открыт|дескриптор|файл))|(?:linux|log|open|открыт|дескриптор|файл).*\brm\b'),
    _Source('Linux umask(2)', 'https://man7.org/linux/man-pages/man2/umask.2.html', r'\bumask\b|маск\w*\s+прав'),
    _Source('Apache Kafka 4.1: design and delivery semantics', 'https://kafka.apache.org/41/design/design/',
            r'\bkafka\b|кафк|\boffset\b|consumer\s+group|партиц'),
    _Source('Apache Kafka 4.1: consumer configuration', 'https://kafka.apache.org/41/configuration/consumer-configs/',
            r'enable[._ ]auto[._ ]commit|auto[._ ]offset[._ ]reset|max[._ ]poll|автокоммит'),
    _Source('RabbitMQ: acknowledgements and publisher confirms', 'https://www.rabbitmq.com/docs/confirms',
            r'rabbitmq|rabbit|рэббит|реббит|publisher\s+confirm|\brequeue\b'),
    _Source('Kubernetes: liveness, readiness and startup probes', 'https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/',
            r'liveness|readiness|startup\s*probe|\bprobes?\b'),
    _Source('Kubernetes: Service', 'https://kubernetes.io/docs/concepts/services-networking/service/',
            r'\bservice\b|сервис|nodeport|clusterip|loadbalancer|endpointslice',
            r'kubernetes|k8s|кубер|nodeport|clusterip|loadbalancer|endpointslice'),
    _Source('TCP: RFC 9293', 'https://www.rfc-editor.org/rfc/rfc9293.txt', r'\btcp\b|\bsyn\b|трехсторон\w*\s+рукопожат'),
    _Source('DNS: RFC 1035', 'https://www.rfc-editor.org/rfc/rfc1035.txt', r'\bdns\b|nxdomain|\bcname\b|разрешен\w*\s+имен'),
    _Source('HTTP semantics: RFC 9110', 'https://www.rfc-editor.org/rfc/rfc9110.txt',
            r'\bhttp\b|\b(?:get|post|put|patch|head|delete|options|etag)\b|идемпот|код\w*\s+статус|статус\w*\s+код|\b(?:100|101|200|201|202|204|206|300|301|302|303|304|307|308|400|401|403|404|405|409|410|412|415|422|429|500|502|503|504)\b'),
    _Source('HTTP PATCH: RFC 5789', 'https://www.rfc-editor.org/rfc/rfc5789.txt', r'\bpatch\b'),
    _Source('JavaScript async functions: MDN', 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/async_function',
            r'\basync\b|\bawait\b|асинхрон|промис'),
    _Source('JavaScript Promise.all: MDN', 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all',
            r'promise[.\s]*all\b|promise[.\s]*allsettled\b'),
)
_BY_URL = {source.url: source for source in _SOURCES}
APPROVED_URLS = frozenset(_BY_URL)
ALLOWED_HOSTS = frozenset(urlsplit(url).hostname for url in APPROVED_URLS)


def is_allowed_url(url):
    """Exact URLs as well as host/scheme are required; no queries or credentials."""
    try:
        value = urlsplit(url)
        return (url in APPROVED_URLS and value.scheme == 'https' and
                value.hostname in ALLOWED_HOSTS and value.port in (None, 443) and
                not value.username and not value.password and not value.query and not value.fragment)
    except (TypeError, ValueError):
        return False


def select_urls(question):
    text = question[:6000].casefold().replace('ё', 'е')
    selected = []
    for index, source in enumerate(_SOURCES):
        if source.scope and not re.search(source.scope, text):
            continue
        matches = re.findall(source.pattern, text)
        if matches:
            selected.append((len(set(matches)), -index, source.url))
    return tuple(url for _, _, url in sorted(selected, reverse=True)[:2])


class _DocumentParser(HTMLParser):
    _void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _excluded = {'script', 'style', 'nav', 'aside', 'footer', 'noscript', 'svg', 'form'}
    _blocks = {'p', 'div', 'section', 'article', 'main', 'pre', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.body, self.main, self.article, self.title = [], [], [], []

    def _visible(self):
        return not any(blocked for _, blocked in self.stack)

    def _append(self, value):
        if not self._visible():
            return
        tags = {tag for tag, _ in self.stack}
        if 'title' in tags:
            self.title.append(value)
        if 'head' in tags:
            return
        self.body.append(value)
        if 'main' in tags:
            self.main.append(value)
        if 'article' in tags:
            self.article.append(value)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get('class', '').lower().split()
        blocked = (tag in self._excluded or attributes.get('aria-hidden') == 'true' or
                   attributes.get('role') in ('navigation', 'banner', 'contentinfo') or
                   any(item in ('navbar', 'sidebar', 'toc', 'breadcrumbs') for item in classes))
        if tag not in self._void:
            self.stack.append((tag, blocked))
        if tag in self._blocks or tag in ('br', 'hr'):
            self._append('\n\n')

    def handle_endtag(self, tag):
        if tag in self._blocks:
            self._append('\n\n')
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self._append(data)

    @staticmethod
    def _clean(chunks):
        lines = [' '.join(line.split()) for line in ''.join(chunks).splitlines()]
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()

    def result(self):
        text = self._clean(self.main) or self._clean(self.article) or self._clean(self.body)
        return self._clean(self.title)[:200], text


def _extract(body, content_type, encoding):
    text = body.decode(encoding or 'utf-8', errors='replace')
    if content_type == 'text/plain':
        return '', text.strip()
    parser = _DocumentParser()
    parser.feed(text)
    parser.close()
    return parser.result()


def _passage_question(question):
    # Local-only lexical expansion for English official documents. These words
    # never enter a request URL, query string, header, body, or cache key.
    text = question.casefold().replace('ё', 'е')
    expansions = (
        (r'идемпот', 'idempotent'),
        (r'безопасн', 'safe methods'),
        (r'аутентифик|неавториз', 'authentication credentials'),
        (r'авториз|доступ', 'authorization forbidden'),
        (r'кэш|кеш', 'cache validation'),
        (r'условн', 'conditional request'),
        (r'открыт', 'open file'),
        (r'удал|\brm\b', 'unlink remove'),
        (r'асинхрон|промис', 'async promise'),
        (r'изоляц', 'isolation'),
    )
    return question + ' ' + ' '.join(hint for pattern, hint in expansions if re.search(pattern, text))


class OnlineReferenceClient:
    def __init__(self, *, transport=None, clock=time.monotonic, request_timeout=8., total_timeout=12., cache_capacity=16):
        if not 0 < request_timeout <= 8 or not 0 < total_timeout <= 12:
            raise ValueError('Reference timeouts must be positive and at most 8/12 seconds')
        if not 1 <= cache_capacity <= MAX_CACHE_ENTRIES:
            raise ValueError('Reference cache capacity must be between 1 and 16')
        self._transport = transport
        self._clock = clock
        self._request_timeout = request_timeout
        self._total_timeout = total_timeout
        self._capacity = cache_capacity
        self._cache = OrderedDict()

    async def _load(self, client, url):
        if not is_allowed_url(url):
            return None
        cached = self._cache.get(url)
        if cached and cached[0] > self._clock():
            self._cache.move_to_end(url)
            return cached[1]
        self._cache.pop(url, None)
        try:
            async with asyncio.timeout(self._request_timeout):
                async with client.stream('GET', url, follow_redirects=False) as response:
                    # Redirects, even to another allowlisted host, are not followed.
                    if response.status_code != 200:
                        return None
                    content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    if content_type not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                        return None
                    try:
                        if int(response.headers.get('content-length', '0')) > MAX_DOCUMENT_BYTES:
                            return None
                    except ValueError:
                        pass
                    chunks, size = [], 0
                    # aiter_bytes applies content decoding; the cap also covers
                    # compressed responses whose decoded body is too large.
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOCUMENT_BYTES:
                            return None
                        chunks.append(chunk)
                    title, text = _extract(b''.join(chunks), content_type, response.encoding)
                    if not text:
                        return None
            document = {'title': title or _BY_URL[url].title, 'url': url, 'text': text}
            self._cache[url] = (self._clock() + CACHE_TTL_SECONDS, document)
            self._cache.move_to_end(url)
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)
            return document
        except (httpx.HTTPError, TimeoutError, UnicodeError, LookupError, ValueError):
            return None

    async def fetch_references(self, question: str) -> list[dict]:
        urls = select_urls(question)
        if not urls:
            return []
        async with httpx.AsyncClient(transport=self._transport, trust_env=False,
                                    timeout=httpx.Timeout(self._request_timeout), follow_redirects=False,
                                    headers={'Accept': 'text/html, text/plain', 'User-Agent': 'AQA-Copilot-Reference/1.0'}) as client:
            tasks = [asyncio.create_task(self._load(client, url)) for url in urls[:2]]
            try:
                _, pending = await asyncio.wait(tasks, timeout=self._total_timeout)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                documents = [task.result() for task in tasks if not task.cancelled() and task.done() and task.exception() is None]
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        return [{'title': document['title'], 'url': document['url'],
                 'text': select_passage(document['text'], _passage_question(question), 1400)}
                for document in documents if document]


_DEFAULT_CLIENT = OnlineReferenceClient()


async def fetch_references(question: str) -> list[dict]:
    """Fetch optional public references; callers decide whether online mode is on."""
    return await _DEFAULT_CLIENT.fetch_references(question)
