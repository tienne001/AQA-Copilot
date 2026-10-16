import test from 'node:test';
import assert from 'node:assert/strict';
test('restored history without a live request does not crash the timing commit',()=>{
  const timing=new UiAnswerTiming();
  assert.equal(timing.commit(undefined),false);
  assert.equal(timing.commit('historic-request'),false);
  assert.deepEqual(timing.snapshot(),{});
});
import {ConversationFlow,applyAnswerEvent,describeAnswerProgress,responseMode,responseModeSettings} from '../src/conversation.mjs';
import {readSSE} from '../src/stream.mjs';

test('automatic start survives an old manual terminal and finally, then renders its tokens and done', () => {
  const flow=new ConversationFlow();
  const ticket=flow.beginManual();
  let messages=[{id:'manual-question',role:'user',content:'Ручной вопрос'}];
  let busy=true;
  const dispatch=(event,origin,ticket)=>{
    const decision=flow.route(event,origin,ticket);
    if(decision.accepted){
      messages=applyAnswerEvent(messages,event,decision.showQuestion);
      if(event.type==='start')busy=true;
      if(decision.finished)busy=false;
    }
    return decision;
  };
  dispatch({type:'start',request_id:'manual'},'manual',ticket);
  const auto=dispatch({type:'start',request_id:'auto',question:'Вопрос из системного звука'},'auto');
  assert.equal(auto.accepted,true);
  assert.equal(ticket.signal.aborted,true);
  assert.equal(auto.showQuestion,true);
  assert.equal(dispatch({type:'cancelled',request_id:'manual'},'manual',ticket).accepted,false);
  if(flow.finishManual(ticket)){
    busy=false;messages=messages.map(m=>({...m,pending:false}));
  }
  assert.equal(busy,true);
  assert.equal(messages.find(m=>m.request_id==='auto').pending,true);
  assert.equal(messages.find(m=>m.id==='auto:question').content,'Вопрос из системного звука');
  dispatch({type:'token',request_id:'auto',text:'Правильный '},'auto');
  dispatch({type:'token',request_id:'auto',text:'ответ'},'auto');
  dispatch({type:'done',request_id:'auto'},'auto');
  assert.equal(busy,false);
  assert.deepEqual(messages.filter(m=>m.request_id==='auto').map(m=>({content:m.content,pending:m.pending})),[{content:'Правильный ответ',pending:false}]);
  assert.equal(messages.find(m=>m.request_id==='manual').pending,false);
});

test('automatic start before manual headers invalidates that manual owner and manual IDs remain deduplicated', () => {
  const flow=new ConversationFlow();
  const pending=flow.beginManual();
  assert.equal(flow.route({type:'start',request_id:'auto',question:'Из аудио'},'auto').accepted,true);
  assert.equal(pending.current(),false);
  assert.equal(flow.route({type:'start',request_id:'late-manual'},'manual',pending).accepted,false);
  assert.equal(flow.finishManual(pending),false);
  const next=flow.beginManual();
  assert.equal(flow.route({type:'start',request_id:'manual-next'},'manual',next).accepted,true);
  assert.equal(flow.route({type:'start',request_id:'manual-next'},'auto').accepted,false);
  assert.equal(next.current(),true);
  assert.equal(flow.route({type:'token',request_id:'auto',text:'Старый токен'},'auto').accepted,false);
});

test('SSE heartbeats keep a blank answer pending without becoming visible answer words or tokens', async () => {
  const flow=new ConversationFlow();
  const ticket=flow.beginManual();
  const events=[
    {type:'start',request_id:'one'},
    {type:'progress',request_id:'one',stage:'online',label:'Читаю официальную документацию',elapsed_ms:3200},
    {type:'progress',request_id:'one',stage:'reasoning',label:'Модель обдумывает вопрос',elapsed_ms:12500},
    {type:'token',request_id:'one',text:'Проверяю правильный ответ.'},
    {type:'progress',request_id:'one',stage:'answer',label:'Формирую ответ',elapsed_ms:13000},
    {type:'done',request_id:'one',metrics:{first_words_ms:12900},sources:[{title:'Источник',path:'https://example.com/docs'}]}
  ];
  const encoded=new TextEncoder().encode(events.map(event=>`data: ${JSON.stringify(event)}\n\n`).join(''));
  const stream=new ReadableStream({start(controller){controller.enqueue(encoded);controller.close();}});
  let messages=[];
  let tokens=0;
  let lastMetrics;
  for await(const event of readSSE(stream,ticket.signal)){
    const decision=flow.route(event,'manual',ticket);
    assert.equal(decision.accepted,true);
    messages=applyAnswerEvent(messages,event,decision.showQuestion);
    if(event.type==='token')tokens++;
    if(event.metrics)lastMetrics=event.metrics;
    if(event.type==='progress'){
      assert.equal(messages[0].pending,true);
      assert.equal(messages[0].content,event.elapsed_ms<13000?'':'Проверяю правильный ответ.');
    }
  }
  assert.equal(tokens,1);
  assert.equal(messages[0].content,'Проверяю правильный ответ.');
  assert.equal(messages[0].pending,false);
  assert.equal(lastMetrics.first_words_ms,12900);
  assert.equal(messages[0].sources[0].path,'https://example.com/docs');
});

test('progress cannot revive completed, cancelled, superseded or unstarted requests', () => {
  for(const terminal of ['done','cancelled','error']){
    const flow=new ConversationFlow();
    const ticket=flow.beginManual();
    assert.equal(flow.route({type:'progress',request_id:'unknown'},'manual',ticket).accepted,false);
    const start={type:'start',request_id:'old'};
    flow.route(start,'manual',ticket);
    let messages=applyAnswerEvent([],start,false);
    const end={type:terminal,request_id:'old'};
    assert.equal(flow.route(end,'manual',ticket).finished,true);
    messages=applyAnswerEvent(messages,end,false);
    const progress={type:'progress',request_id:'old',stage:'answer',label:'Late',elapsed_ms:90000};
    assert.equal(flow.route(progress,'manual',ticket).accepted,false);
    assert.equal(flow.route({type:'token',request_id:'old',text:'Late'},'manual',ticket).accepted,false);
    assert.equal(flow.route(end,'manual',ticket).accepted,false);
    assert.equal(applyAnswerEvent(messages,progress,false)[0],messages[0]);
    const auto={type:'start',request_id:'new'};
    assert.equal(flow.route(auto,'auto').accepted,true);
    assert.equal(flow.route(progress,'manual',ticket).accepted,false);
    assert.equal(flow.route({...progress,request_id:'new'},'auto').accepted,true);
    flow.cancel();
    assert.equal(flow.route({...progress,request_id:'new'},'auto').accepted,false);
  }
});

test('progress clock is monotonic, handles malformed elapsed time and explains the 3s and 12s thresholds', () => {
  let messages=applyAnswerEvent([],{type:'start',request_id:'one'},false);
  const progress=elapsed_ms=>({type:'progress',request_id:'one',stage:'model',label:'Модель готовит ответ',elapsed_ms});
  for(const [elapsed,notice] of [[2999,''],[3000,'Подготовка ответа продолжается.'],[11999,'Подготовка ответа продолжается.'],[12000,'Ответ занимает больше обычного. Работа продолжается.']]){
    messages=applyAnswerEvent(messages,progress(elapsed),false);
    const view=describeAnswerProgress(messages[0]);
    assert.equal(view.seconds,Math.floor(elapsed/1000));
    assert.equal(view.label,'Модель готовит ответ');
    assert.equal(view.notice,notice);
  }
  const at12=messages[0];
  messages=applyAnswerEvent(messages,{...progress(1000),stage:'context',label:'Старый этап'},false);
  assert.equal(messages[0],at12);
  for(const elapsed of [-1,NaN,Infinity,'20000']){
    messages=applyAnswerEvent(messages,{...progress(elapsed),label:''},false);
    assert.equal(messages[0].progress.elapsed_ms,12000);
    assert.equal(messages[0].progress.label,'Модель готовит ответ');
  }
  messages=applyAnswerEvent(messages,{type:'token',request_id:'one',text:'Ответ уже появляется'},false);
  assert.equal(describeAnswerProgress({...messages[0],progress:{...messages[0].progress,elapsed_ms:5000}}).notice,'');
  assert.match(describeAnswerProgress(messages[0]).notice,/больше обычного/);
});

test('single response mode keeps reasoning and adaptive flags consistent without changing online consent', () => {
  const expected={fast:[false,false],accurate:[true,false],auto:[true,true]};
  for(const online_reference_enabled of [false,true]){
    let settings={reasoning_enabled:true,adaptive_reasoning:true,online_reference_enabled};
    for(const mode of ['fast','accurate','auto','accurate','fast']){
      settings={...settings,...responseModeSettings(mode)};
      assert.equal(responseMode(settings),mode);
      assert.deepEqual([settings.reasoning_enabled,settings.adaptive_reasoning],expected[mode]);
      assert.equal(settings.online_reference_enabled,online_reference_enabled);
    }
  }
  assert.equal(responseMode({reasoning_enabled:true}),'accurate');
  assert.equal(responseMode({reasoning_enabled:false,adaptive_reasoning:true}),'fast');
});

import {UiAnswerTiming,beginPendingAnswer} from '../src/conversation.mjs';

test('manual pending appears before headers and binds to server start without duplicate question',()=>{
  const flow=new ConversationFlow();const ticket=flow.beginManual();
  let messages=beginPendingAnswer([],ticket.pendingId,'Question');
  assert.equal(messages.length,2);assert.equal(messages[1].pending,true);
  assert.equal(messages[1].progress.stage,'connecting');
  const event={type:'start',request_id:'server'};
  const decision=flow.route(event,'manual',ticket);
  messages=applyAnswerEvent(messages,{...event,pending_id:decision.pendingId},false);
  assert.equal(messages.length,2);assert.equal(messages[1].request_id,'server');
});

test('UI timing uses local elapsed time, ignores stale events and measures commit separately',()=>{
  let now=100;const timing=new UiAnswerTiming(()=>now);
  timing.begin('pending');now=450;
  timing.receive({type:'start',request_id:'server',elapsed_ms:999999},'pending');
  now=600;timing.receive({type:'token',request_id:'server',text:'answer',elapsed_ms:3});
  now=620;assert.equal(timing.commit('server'),true);
  now=700;timing.receive({type:'done',request_id:'server'});
  const m=timing.snapshot();assert.equal(m.first_token_received_ms,500);
  assert.equal(m.first_content_commit_ms,520);assert.equal(m.total_ms,600);
  timing.begin('new');timing.receive({type:'error',request_id:'server'});
  assert.equal(timing.snapshot().outcome,'pending');assert.equal(timing.commit('server'),false);
});

test('UI preheader failure and automatic origins are explicit',()=>{
  let now=0;const timing=new UiAnswerTiming(()=>now);
  timing.begin('pending');now=400;timing.finish('error');
  assert.equal(timing.snapshot().total_ms,400);
  assert.equal(timing.snapshot().first_token_received_ms,null);
  timing.receive({type:'start',request_id:'auto'});
  assert.equal(timing.snapshot().origin,'auto');
  assert.equal(timing.snapshot().first_event_ms,0);
});

import {mergeMetricsSnapshot} from '../src/conversation.mjs';
test('late metrics poll cannot replace a newer request or regress done to pending',()=>{
  const current={gpu:{used_mb:1},latest:{request_id:'new',outcome:'done',total_ms:123}};
  const stale={gpu:{used_mb:2},latest:{request_id:'old',outcome:'done',total_ms:456}};
  const merged=mergeMetricsSnapshot(current,stale,'new');
  assert.equal(merged.gpu.used_mb,2);assert.equal(merged.latest.total_ms,123);
  assert.equal(mergeMetricsSnapshot(current,{latest:{request_id:'new',outcome:'pending'}},'new').latest.outcome,'done');
  assert.equal(mergeMetricsSnapshot({},stale,undefined).latest.request_id,'old');
});

test('manual preheader wait and notice survive binding to server start',()=>{
  const flow=new ConversationFlow();const ticket=flow.beginManual();
  let messages=beginPendingAnswer([],ticket.pendingId,'Question',100);
  assert.equal(describeAnswerProgress(messages[1],3200).seconds,3);
  const event={type:'start',request_id:'server'};
  const decision=flow.route(event,'manual',ticket);
  messages=applyAnswerEvent(messages,{...event,pending_id:decision.pendingId},false,3200);
  const answer=messages.find(m=>m.request_id==='server');
  assert.equal(answer.id,ticket.pendingId); // React retains the existing keyed row.
  assert.equal(answer.client_started_at,100);
  let progress=describeAnswerProgress(answer,3200);
  assert.equal(progress.seconds,3);
  assert.equal(progress.notice,'Подготовка ответа продолжается.');
  // The first Python heartbeat starts near zero; the browser wait cannot rewind.
  messages=applyAnswerEvent(messages,{type:'progress',request_id:'server',elapsed_ms:7,label:'Модель готовит ответ'},false,3300);
  progress=describeAnswerProgress(messages.find(m=>m.request_id==='server'),3300);
  assert.equal(progress.seconds,3);assert.ok(progress.notice);
  assert.equal(describeAnswerProgress(messages[1],12200).seconds,12);
});

test('auto start replacing a manual wait starts its own browser progress clock',()=>{
  const messages=beginPendingAnswer([],'pending','Manual',100);
  const next=applyAnswerEvent(messages,{type:'start',request_id:'auto',pending_id:'pending',question:'Auto'},true,5000);
  const answer=next.find(m=>m.request_id==='auto');
  assert.equal(answer.id,'auto');
  assert.equal(answer.client_started_at,5000);
  assert.equal(describeAnswerProgress(answer,5000).seconds,0);
});

test('auto replacement has its own timing origin even while removing manual provisional row',()=>{
  let now=100;const timing=new UiAnswerTiming(()=>now);
  const flow=new ConversationFlow();const ticket=flow.beginManual();
  timing.begin(ticket.pendingId);
  now=4100;
  const event={type:'start',request_id:'auto',question:'Audio question'};
  const decision=flow.route(event,'auto');
  assert.equal(decision.pendingId,ticket.pendingId);
  timing.receive(event,decision.pendingId,'auto');
  assert.equal(timing.snapshot().origin,'auto');
  assert.equal(timing.snapshot().first_event_ms,0);
  now=4300;timing.receive({type:'token',request_id:'auto',text:'Answer'},undefined,'auto');
  assert.equal(timing.snapshot().first_token_received_ms,200);
  now=4500;timing.receive({type:'done',request_id:'auto'},undefined,'auto');
  assert.equal(timing.snapshot().total_ms,400);
  timing.receive({type:'error',request_id:'old-manual'},undefined,'manual');
  assert.equal(timing.snapshot().outcome,'done');
});

test('manual start explicitly retains submission origin and preheader wait',()=>{
  let now=10;const timing=new UiAnswerTiming(()=>now);
  timing.begin('pending');now=3010;
  timing.receive({type:'start',request_id:'manual'},'pending','manual');
  assert.equal(timing.snapshot().origin,'manual');
  assert.equal(timing.snapshot().first_event_ms,3000);
});
