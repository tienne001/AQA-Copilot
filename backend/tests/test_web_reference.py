import asyncio
import time

import httpx
import pytest

from copilot.web_reference import (APPROVED_URLS, CACHE_TTL_SECONDS, MAX_DOCUMENT_BYTES,
                                   OnlineReferenceClient, is_allowed_url, select_urls)


def html(text):
    return '<html><head><title>Official Reference</title></head><body><nav>NAV_PRIVATE</nav><main><p>' + text + '</p></main><script>SCRIPT_PRIVATE</script></body></html>'


def test_all_fixed_sources_are_https_and_question_urls_cannot_expand_allowlist():
    assert all(is_allowed_url(url) for url in APPROVED_URLS)
    assert not is_allowed_url('http://www.postgresql.org/docs/current/transaction-iso.html')
    assert not is_allowed_url('https://www.postgresql.org/unknown')
    assert not is_allowed_url('https://www.postgresql.org/docs/current/transaction-iso.html?resume=secret')
    assert not is_allowed_url('https://user:secret@www.postgresql.org/docs/current/transaction-iso.html')
    assert not is_allowed_url('https://www.postgresql.org.evil.test/docs/current/transaction-iso.html')
    assert select_urls('https://evil.test/private-resume') == ()


@pytest.mark.parametrize('question,expected_path', [
    ('Почему PUT идемпотентен, а POST нет?', '/rfc/rfc9110.txt'),
    ('Чем отличаются HTTP 401 и 403?', '/rfc/rfc9110.txt'),
    ('304 ETag и условные запросы', '/rfc/rfc9110.txt'),
    ('PUT против PATCH', '/rfc/rfc5789.txt'),
    ('Что такое POM в Playwright?', '/docs/pom'),
    ('Как BrowserContext изолирует cookie?', '/docs/browser-contexts'),
    ('Playwright waitForResponse после клика', '/docs/network'),
    ('Для чего async await?', '/Reference/Statements/async_function'),
    ('Как работает Promise.all?', '/Reference/Global_Objects/Promise/all'),
    ('Удалили app.log через rm, файл остаётся открытым в Linux', '/man2/unlink.2.html'),
])
def test_general_stack_topic_coverage(question, expected_path):
    assert any(url.endswith(expected_path) for url in select_urls(question))


def test_russian_idempotency_question_selects_english_fact_instead_of_rfc_preamble():
    answer = 'A request method is considered idempotent when repeated identical requests have the same intended effect.'
    def handler(request):
        text = 'RFC 9110 Introduction.\n\n' + ('General protocol introduction. ' * 100) + '\n\n' + answer
        return httpx.Response(200, headers={'content-type': 'text/plain'}, text=text)
    result = asyncio.run(OnlineReferenceClient(transport=httpx.MockTransport(handler)).fetch_references('Что значит идемпотентность?'))
    assert len(result) == 1 and answer in result[0]['text']


def test_fetch_uses_only_two_fixed_gets_and_never_sends_private_question_or_follows_links():
    captured = []
    private = 'RESUME_OCR_HISTORY_PRIVATE_123456'
    async def handler(request):
        captured.append(request)
        return httpx.Response(200, headers={'content-type': 'text/html'},
                              text=html('chmod chown umask unlink: official reference. <a href="https://evil.test/">link</a>'))
    async def scenario():
        client = OnlineReferenceClient(transport=httpx.MockTransport(handler))
        result = await client.fetch_references('chmod chown umask unlink ' + private)
        assert len(result) == len(captured) == 2
        assert all(set(item) == {'title', 'url', 'text'} for item in result)
        assert all('NAV_PRIVATE' not in item['text'] and 'SCRIPT_PRIVATE' not in item['text'] for item in result)
        for request in captured:
            assert request.method == 'GET' and request.content == b''
            assert str(request.url) in APPROVED_URLS and not request.url.query
            assert private not in str(request.url) + str(request.headers)
            assert 'authorization' not in request.headers and 'referer' not in request.headers
    asyncio.run(scenario())


def test_main_article_priority_navigation_removal_and_paragraph_selection():
    answer = 'Read Uncommitted в PostgreSQL ведёт себя как Read Committed.'
    async def handler(request):
        page = '<html><body><nav>Read Uncommitted NAV_WRONG</nav><article>ARTICLE_WRONG</article><main>'
        page += '<style>STYLE_WRONG</style><p>' + ('General introduction. ' * 100) + '</p><p>' + answer + '</p></main>BODY_WRONG</body></html>'
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=page)
    result = asyncio.run(OnlineReferenceClient(transport=httpx.MockTransport(handler)).fetch_references('Read Uncommitted PostgreSQL'))
    assert len(result) == 1 and answer in result[0]['text']
    assert 'WRONG' not in result[0]['text'] and len(result[0]['text']) <= 1400


def test_redirect_is_rejected_without_fetching_location():
    captured = []
    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(302, headers={'location': 'https://evil.test/private'})
    result = asyncio.run(OnlineReferenceClient(transport=httpx.MockTransport(handler)).fetch_references('chmod'))
    assert result == [] and len(captured) == 1


def test_payload_size_cap_applies_without_content_length():
    class Oversized(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'<main>chmod ' + b'x' * (MAX_DOCUMENT_BYTES // 2)
            yield b'y' * (MAX_DOCUMENT_BYTES // 2)
    def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/html'}, stream=Oversized())
    assert asyncio.run(OnlineReferenceClient(transport=httpx.MockTransport(handler)).fetch_references('chmod')) == []


def test_declared_oversize_is_not_read():
    class MustNotRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError('Oversized declared body must not be read')
            yield b''
    def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/html', 'content-length': str(MAX_DOCUMENT_BYTES + 1)}, stream=MustNotRead())
    assert asyncio.run(OnlineReferenceClient(transport=httpx.MockTransport(handler)).fetch_references('chmod')) == []


def test_one_failed_document_does_not_discard_successful_reference():
    def handler(request):
        if 'chown.' in request.url.path:
            raise httpx.ConnectError('offline', request=request)
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=html('chmod controls permissions.'))
    result = asyncio.run(OnlineReferenceClient(transport=httpx.MockTransport(handler)).fetch_references('chmod chown'))
    assert len(result) == 1 and 'chmod.' in result[0]['url']


def test_cache_ttl_uses_url_only_and_selects_a_new_passage_for_each_question():
    now, calls = [100.], []
    def handler(request):
        calls.append(str(request.url))
        page = '<main><p>COUNT_MARKER COUNT counts non-null values.</p><p>' + ('General introduction. ' * 100) + '</p><p>SUM_MARKER SUM adds values.</p></main>'
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=page)
    async def scenario():
        client = OnlineReferenceClient(transport=httpx.MockTransport(handler), clock=lambda: now[0])
        first = await client.fetch_references('COUNT')
        second = await client.fetch_references('SUM')
        assert 'COUNT_MARKER' in first[0]['text'] and 'SUM_MARKER' in second[0]['text']
        assert len(calls) == 1
        now[0] += CACHE_TTL_SECONDS + 1
        await client.fetch_references('COUNT')
        assert len(calls) == 2
    asyncio.run(scenario())


def test_cache_is_lru_bounded_and_construction_has_no_network_io():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=html('chmod chown umask'))
    async def scenario():
        client = OnlineReferenceClient(transport=httpx.MockTransport(handler), cache_capacity=2)
        assert calls == []
        for question in ('chmod', 'chown', 'umask', 'chmod'):
            await client.fetch_references(question)
        assert len(calls) == 4 and len(client._cache) == 2
    asyncio.run(scenario())


def test_total_timeout_keeps_finished_document_and_cancels_pending_fetch():
    cancelled = []
    async def handler(request):
        if 'chown.' in request.url.path:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=html('chmod permissions.'))
    async def scenario():
        client = OnlineReferenceClient(transport=httpx.MockTransport(handler), request_timeout=.2, total_timeout=.04)
        result = await asyncio.wait_for(client.fetch_references('chmod chown'), .5)
        assert len(result) == 1 and cancelled == [True]
    asyncio.run(scenario())


def test_request_deadline_handles_continuously_slow_document():
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=html('chmod'))
    async def scenario():
        client = OnlineReferenceClient(transport=httpx.MockTransport(handler), request_timeout=.02, total_timeout=.2)
        assert await asyncio.wait_for(client.fetch_references('chmod'), .5) == []
    asyncio.run(scenario())


def test_unknown_topic_and_plaintext_rfc_support():
    captured = []
    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/plain'}, text='TCP uses sequence numbers and acknowledgements.')
    async def scenario():
        client = OnlineReferenceClient(transport=httpx.MockTransport(handler))
        assert await client.fetch_references('Unrelated private resume') == []
        assert captured == []
        result = await client.fetch_references('TCP sequence numbers')
        assert len(result) == 1 and 'TCP' in result[0]['text']
    asyncio.run(scenario())


@pytest.mark.parametrize('kwargs', [{'request_timeout': 9}, {'total_timeout': 13}, {'cache_capacity': 17}, {'cache_capacity': 0}])
def test_resource_bounds_cannot_be_disabled(kwargs):
    with pytest.raises(ValueError):
        OnlineReferenceClient(**kwargs)
