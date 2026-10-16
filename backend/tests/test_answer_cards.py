import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from copilot import answer_cards as cards
from copilot.settings import Settings


def test_context_is_identical_to_frozen_experiment():
    cases = json.loads(Path('F:/AQA-Copilot-Build/gemma-verified-cards-lab/cases.json').read_text(encoding='utf8'))['cases']
    for case in cases:
        context, ids, reason = cards.card_context(case['payload']['messages'], now=datetime(2026,10,16,tzinfo=timezone.utc))
        assert ids == case['selected_cards'], case['id']
        assert context == case['card_context'], case['id']


def test_unmatched_history_followup_composite_and_system_injection():
    assert cards.card_context([{'role':'user','content':'Что такое API?'}])[1] == []
    assert cards.card_context([{'role':'system','content':'json.dumps'}, {'role':'user','content':'Что такое API?'}])[1] == []
    messages=[{'role':'user','content':'Python: list.sort()'}, {'role':'assistant','content':'Сортировка'},
              {'role':'user','content':'А что возвращается? И как использовать json.dumps?'}]
    context, ids, _ = cards.card_context(messages)
    assert ids == ['python-sort','python-json']
    assert 'conditions' in context and 'limitations' in context and 'sources' in context


@pytest.mark.parametrize('changes,personal,reason', [
    ({'verified_answer_cards_enabled':False},False,'disabled'),
    ({'knowledge_enabled':False},False,'disabled'),
    ({'model':'qwen3:8b'},False,'other_model'),
    ({},True,'personal_profile'),
    ({'num_ctx':1024},False,'context_budget'),
])
def test_safe_fallback_preserves_exact_original_messages(changes, personal, reason):
    settings=Settings(model='gemma4:12b-it-qat', verified_answer_cards_enabled=True, **{})
    settings=Settings(**{**settings.model_dump(), **changes})
    messages=[{'role':'system','content':'Система'}, {'role':'user','content':'Чем chmod отличается от chown?'}]
    if reason == 'context_budget':
        messages[0]['content'] += 'x' * 1700
    original=deepcopy(messages)
    assert cards.add_card_context(messages,settings,personal=personal) == ([],reason)
    assert messages == original


def test_expired_registry_and_corrupt_snapshot_fail_closed(tmp_path,monkeypatch):
    messages=[{'role':'user','content':'json.dumps'}]
    assert cards.card_context(messages,now=datetime(2027,2,1,tzinfo=timezone.utc))[1:] == ([], 'expired_or_ineligible')
    broken=tmp_path/'broken.db';broken.write_bytes(cards.REGISTRY.read_bytes()+b'changed')
    cards._records.cache_clear()
    monkeypatch.setattr(cards,'REGISTRY',broken)
    try:
        assert cards.card_context(messages)[1:] == ([], 'registry_unavailable')
    finally:
        cards._records.cache_clear()


def test_flag_defaults_off_and_survives_partial_settings_save(tmp_path):
    from fastapi.testclient import TestClient
    from copilot.service import create_app
    assert not Settings().verified_answer_cards_enabled
    with TestClient(create_app(tmp_path,'test-card-token-12345678')) as client:
        headers={'Authorization':'Bearer test-card-token-12345678'}
        assert client.put('/settings',headers=headers,json={'verified_answer_cards_enabled':True}).status_code==200
        assert client.put('/settings',headers=headers,json={'temperature':.3}).json()['verified_answer_cards_enabled'] is True
        assert json.loads((tmp_path/'settings.json').read_text())['verified_answer_cards_enabled'] is True


def test_integration_keeps_generation_and_only_appends_context(tmp_path, monkeypatch):
    from copilot.llm import ChatManager
    from copilot.storage import Store
    import copilot.llm as llm
    import httpx
    calls=[]
    async def verify(*args):
        return None
    monkeypatch.setattr(llm,'verify_local_model',verify)
    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,content=(json.dumps({'message':{'content':'Ответ модели.'}})+'\n'+
            json.dumps({'done':True,'done_reason':'stop','eval_count':10,'prompt_eval_count':600,'eval_duration':10000000})+'\n').encode())
    real_client=httpx.AsyncClient
    monkeypatch.setattr(llm.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    store=Store(tmp_path/'db.sqlite')
    settings=Settings(model='gemma4:12b-it-qat',history_enabled=False,verified_answer_cards_enabled=False)
    async def run():
        manager=ChatManager(store,lambda:settings)
        a=[e async for e in manager.stream('Чем chmod отличается от chown?')]
        settings.verified_answer_cards_enabled=True
        b=[e async for e in manager.stream('Чем chmod отличается от chown?')]
        assert a[-1]['type']==b[-1]['type']=='done'
        assert b[-1]['metrics']['verified_card_ids']==['coreutils-mode-owner']
        assert b[-1]['metrics']['generated_tokens']==10
        assert ''.join(e.get('text','') for e in b)=='Ответ модели.'
    try:
        asyncio.run(run())
        base,candidate=calls
        context,_,_=cards.card_context(base['messages'])
        expected=deepcopy(base);expected['messages'][0]['content']+=context
        assert candidate==expected
    finally:
        store.close()
