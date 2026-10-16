import {useCallback,useEffect,useRef,useState} from 'react';
import {listen} from '@tauri-apps/api/event';
import {invoke} from '@tauri-apps/api/core';
import {Api,connectionInfo,type Capture,type Devices,type Event,type Knowledge,type Message,type Metrics,type Session,type Settings,type WindowItem} from './api';
import {RequestGate,CancelBarrier} from './stream.mjs';
import {ConversationFlow,mergeMetricsSnapshot,UiAnswerTiming,beginPendingAnswer,applyAnswerEvent,describeAnswerProgress,responseMode,responseModeSettings} from './conversation.mjs';
import {describeHealth} from './health.mjs';
import {resetConversationContext} from './context-reset.mjs';
import {applyTheme,type Theme} from './theme';
import {FormattedAnswer} from './FormattedAnswer';

const emptyDevices:Devices={loopback:[],microphone:[],default_loopback:null,default_microphone:null};
const ms=(n:unknown)=>typeof n==='number'?`${n>=1000?(n/1000).toFixed(2):Math.round(n)} ${n>=1000?'с':'мс'}`:'—';
const errorText=(e:unknown)=>e instanceof Error?e.message:String(e);
const examples=['Как надёжно дождаться ответа API в Playwright?','Разбери причину flaky-теста и предложи проверку','Чем отличаются smoke, regression и sanity?'];
type Tab='chat'|'knowledge'|'settings';

export default function App(){
  const [theme,setTheme]=useState<Theme>(()=>document.documentElement.dataset.theme==='light'?'light':'dark');
  const [api,setApi]=useState<Api>();
  const [tab,setTab]=useState<Tab>('chat');
  const [status,setStatus]=useState('Подключение к локальному сервису');
  const [error,setError]=useState('');
  const [nativeWarnings,setNativeWarnings]=useState('');
  const [capturePrivacy,setCapturePrivacy]=useState<boolean|null>(null);
  const [privacyBusy,setPrivacyBusy]=useState(false);
  const privacyPending=useRef(false);
  const [notice,setNotice]=useState('');
  const [ready,setReady]=useState(false);
  const [health,setHealth]=useState<Record<string,unknown>>({});
  const [settings,setSettings]=useState<Settings>();
  const [devices,setDevices]=useState<Devices>(emptyDevices);
  const [selected,setSelected]=useState<{loopback:number|null;microphone:number|null}>({loopback:null,microphone:null});
  const [audio,setAudio]=useState({loopback:false,microphone:false});
  const [levels,setLevels]=useState({loopback:0,microphone:0});
  const [audioBusy,setAudioBusy]=useState('');
  const [transcripts,setTranscripts]=useState<{source:string;text:string;raw?:string}[]>([]);
  const [windows,setWindows]=useState<WindowItem[]>([]);
  const [windowId,setWindowId]=useState('');
  const [capture,setCapture]=useState<Capture>();
  const [attach,setAttach]=useState(false);
  const [captureBusy,setCaptureBusy]=useState(false);
  const [sessions,setSessions]=useState<Session[]>([]);
  const [sessionId,setSessionId]=useState<string>();
  const [sessionLoading,setSessionLoading]=useState(false);
  const [contextClearing,setContextClearing]=useState(false);
  const [eventsEpoch,setEventsEpoch]=useState(0);
  const contextResetPending=useRef(false);
  const eventsController=useRef<AbortController|undefined>(undefined);
  const eventsConnected=useRef<(()=>void)|undefined>(undefined);
  const [messages,setMessages]=useState<Message[]>([]);
  const [question,setQuestion]=useState('');
  const [busy,setBusy]=useState(false);
  const [metrics,setMetrics]=useState<Metrics>({});
  const [warmup,setWarmup]=useState(false);
  const [saving,setSaving]=useState(false);
  const [search,setSearch]=useState('');
  const [results,setResults]=useState<Knowledge[]>([]);
  const [importTitle,setImportTitle]=useState('');
  const [importText,setImportText]=useState('');
  const [importProfile,setImportProfile]=useState(false);
  const [knowledgeBusy,setKnowledgeBusy]=useState(false);
  const conversation=useRef(new ConversationFlow());
  const uiTiming=useRef(new UiAnswerTiming());
  const [uiMetrics,setUiMetrics]=useState<Record<string,unknown>>({});
  const captureGate=useRef(new RequestGate());
  const cancellation=useRef(new CancelBarrier());
  const currentSession=useRef<string|undefined>(undefined);
  const scroll=useRef<HTMLDivElement>(null);
  const captureAction=useRef<()=>void>(()=>{});
  const cancelAction=useRef<()=>void>(()=>{});
  const historyGate=useRef(0);

  useEffect(()=>{let live=true;if('__TAURI_INTERNALS__' in window)void invoke<boolean>('capture_privacy').then(value=>{if(live)setCapturePrivacy(value);}).catch(e=>{if(live)setError(errorText(e));});return()=>{live=false;};},[]);
  const toggleCapturePrivacy=async()=>{
    if(capturePrivacy===null||privacyPending.current)return;
    privacyPending.current=true;setPrivacyBusy(true);
    try{setCapturePrivacy(await invoke<boolean>('set_capture_privacy',{enabled:!capturePrivacy}));}
    catch(e){setError(errorText(e));}
    finally{privacyPending.current=false;setPrivacyBusy(false);}
  };

  useEffect(()=>{let alive=true; connectionInfo().then(c=>{if(alive)setApi(new Api(c));}).catch(e=>{if(alive){setError(errorText(e));setStatus('Сервис недоступен');}});return()=>{alive=false;};},[]);
  const refreshSessions=useCallback(async()=>{if(api)setSessions(await api.json<Session[]>('/sessions'));},[api]);
  const refreshInputs=useCallback(async()=>{if(!api)return;const [d,w]=await Promise.all([api.json<Devices>('/devices'),api.json<WindowItem[]>('/windows')]);setDevices(d);setWindows(w);setSelected(s=>({loopback:s.loopback??d.default_loopback,microphone:s.microphone??d.default_microphone}));},[api]);
  const consume=useCallback((event:Event,origin:'auto'|'manual',ticket?:ReturnType<RequestGate['begin']>)=>{
    if(event.type==='connected'){eventsConnected.current?.();return;}
    if(contextResetPending.current)return;
    const decision=conversation.current.route(event,origin,ticket);
    if(!decision.accepted)return;
    if(event.type==='audio_level' && (event.source==='loopback'||event.source==='microphone')){setLevels(v=>({...v,[event.source!]:Math.max(0,Math.min(1,Number(event.level??0)))}));return;}
    if(event.type==='audio_error'||event.type==='error'){setError(String(event.error??'Ошибка локального сервиса'));if(event.source==='loopback'||event.source==='microphone')setAudio(v=>({...v,[event.source!]:false}));}
    if(event.type==='transcript'&&event.text){setTranscripts(v=>[...v.slice(-7),{source:String(event.source),text:event.text!,raw:event.raw_text}]);}
    if(event.type==='metrics'){setMetrics(v=>mergeMetricsSnapshot(v,event.metrics??{},uiTiming.current.current?.request_id));}
    if(!event.request_id)return;
    if(event.type==='start'){
      if(event.session_id){currentSession.current=event.session_id;setSessionId(event.session_id);}
      setBusy(true);setMetrics(v=>({...v,latest:{request_id:event.request_id,outcome:'pending'}}));
    }
    uiTiming.current.receive(event,decision.pendingId,origin);
    setUiMetrics(uiTiming.current.snapshot());
    setMessages(v=>applyAnswerEvent(v,{...event,pending_id:decision.pendingId},decision.showQuestion));
    if(event.type==='done'||event.type==='error'||event.type==='cancelled'){
      if(decision.finished)setBusy(false);
      if(event.metrics)setMetrics(v=>({...v,latest:event.metrics}));
      void refreshSessions().catch(()=>{});
    }
  },[refreshSessions]);
  useEffect(()=>{
    if(!api)return;
    let live=true; const controller=new AbortController(); let delay:ReturnType<typeof setTimeout>|undefined;
    eventsController.current=controller;
    const retry=(time:number)=>new Promise<void>(resolve=>{delay=setTimeout(resolve,time);});
    async function start(){
      let initialized=false;
      while(live&&!initialized){
        try{
          const h=await api!.json<Record<string,unknown>>('/health',undefined,controller.signal);if(!live)return;
          setHealth(h);const state=describeHealth(h);setReady(state.ready);setStatus(state.status);
          const s=await api!.json<Settings>('/settings',undefined,controller.signal);if(!live)return;setSettings(s);
          await Promise.all([refreshInputs(),refreshSessions()]);initialized=true;
        }catch(e){if(!live||controller.signal.aborted)return;setStatus('Ожидание локального сервиса');setError(errorText(e));await retry(2000);}
      }
      if(initialized&&live)setError('');
      while(live){
        try{for await(const event of api!.events('/events',undefined,controller.signal)){if(!live)return;consume(event,'auto');}}
        catch(e){if(!live||controller.signal.aborted)return;setError(`Поток событий прерван: ${errorText(e)}`);}
        if(live)await retry(2000);
      }
    }
    void start();
    const poll=setInterval(()=>{
      void api.json<Metrics>('/metrics',undefined,controller.signal).then(m=>{if(live){setMetrics(v=>mergeMetricsSnapshot(v,m,uiTiming.current.current?.request_id));if(m.audio)setAudio(m.audio);}}).catch(()=>{});
      void api.json<Record<string,unknown>>('/health',undefined,controller.signal).then(h=>{if(live){setHealth(h);const state=describeHealth(h);setReady(state.ready);setStatus(state.status);}}).catch(()=>{if(live){setReady(false);setStatus('Нет связи с сервисом');}});
    },4000);
    return()=>{live=false;controller.abort();clearInterval(poll);if(delay)clearTimeout(delay);};
  },[api,consume,refreshInputs,refreshSessions,eventsEpoch]);
  // A heartbeat changes status only; do not pull the reader down every second.
  const answerScrollKey=messages.map(m=>`${m.id}:${m.content.length}:${m.pending}`).join('|');
  useEffect(()=>{
    const current=messages.find(m=>m.request_id===uiTiming.current.current?.request_id&&m.content);
    if(current&&uiTiming.current.commit(current.request_id))setUiMetrics(uiTiming.current.snapshot());
  },[messages]);
  useEffect(()=>{scroll.current?.scrollIntoView({behavior:'smooth'});},[answerScrollKey]);
  useEffect(()=>{
    if(!('__TAURI_INTERNALS__' in window))return;
    let disposed=false;const unlisten:(()=>void)[]=[];
    for(const event of ['capture-selected','cancel','shortcut-error'])void listen<string>(event,e=>{if(event==='capture-selected')captureAction.current();else if(event==='cancel')cancelAction.current();else setNativeWarnings(e.payload);}).then(fn=>disposed?fn():unlisten.push(fn));
    void invoke<string[]>('native_warnings').then(w=>{if(w.length)setNativeWarnings(w.join('\n'));}).catch(e=>setNativeWarnings(errorText(e)));
    return()=>{disposed=true;unlisten.forEach(fn=>fn());};
  },[]);
  const cancel=useCallback(async()=>{conversation.current.cancel();uiTiming.current.finish('cancelled');setUiMetrics(uiTiming.current.snapshot());setBusy(false);setMessages(v=>v.map(m=>({...m,pending:false})));try{await cancellation.current.run(()=>api?.json('/cancel',{}));}catch(e){setError(errorText(e));}},[api]);
  cancelAction.current=()=>{void cancel();};
  const send=async(value=question)=>{
    if(!api||!value.trim()||sessionLoading||contextResetPending.current)return;
    const ticket=conversation.current.beginManual();setBusy(true);setError('');setQuestion('');
    uiTiming.current.begin(ticket.pendingId);setUiMetrics(uiTiming.current.snapshot());
    setMetrics(v=>({...v,latest:{request_id:ticket.pendingId,outcome:'pending'}}));
    setMessages(v=>beginPendingAnswer(v,ticket.pendingId,value.trim()));
    await cancellation.current.settled();if(!ticket.current())return;
    const ocr=attach?capture?.text:undefined;setAttach(false);
    try{
      for await(const event of api.events('/chat',{question:value.trim(),session_id:currentSession.current,ocr_context:ocr},ticket.signal))consume(event,'manual',ticket);
      if(ticket.current()&&uiTiming.current.current?.outcome==='pending')throw new Error('Поток ответа завершился без итогового события.');
    }catch(e){if(ticket.current()){setError(errorText(e));uiTiming.current.finish('error');setUiMetrics(uiTiming.current.snapshot());}}
    finally{if(conversation.current.finishManual(ticket)){uiTiming.current.finish('cancelled');setUiMetrics(uiTiming.current.snapshot());setBusy(false);setMessages(v=>v.map(m=>({...m,pending:false})));}}
  };
  const switchSession=async(id?:string)=>{
    if(contextResetPending.current||contextClearing)return;
    const generation=++historyGate.current;setSessionLoading(true);await cancel();currentSession.current=id;setSessionId(id);setTab('chat');
    try{if(!id){setMessages([]);if(api){const session=await api.json<{id:string}>('/sessions',{});if(generation===historyGate.current){currentSession.current=session.id;setSessionId(session.id);await refreshSessions();}}return;}const h=await api!.json<Message[]>(`/history?session_id=${encodeURIComponent(id)}`);if(generation===historyGate.current)setMessages(h.map(m=>({...m,id:crypto.randomUUID()})));}catch(e){setError(errorText(e));}finally{if(generation===historyGate.current)setSessionLoading(false);}
  };
  const clearContext=async()=>{
    if(!api||contextResetPending.current||sessionLoading||audioBusy)return;
    contextResetPending.current=true;setContextClearing(true);setSessionLoading(true);setError('');setNotice('');
    historyGate.current++;captureGate.current.cancel();setCaptureBusy(false);
    eventsController.current?.abort();
    const channels=(['loopback','microphone'] as const).filter(source=>audio[source]).map(source=>({source,device_index:selected[source]}));
    let reconnectRequested=false;
    try{
      await cancel();
      const result=await resetConversationContext(api,channels,{
        stopped:()=>{setAudio({loopback:false,microphone:false});setLevels({loopback:0,microphone:0});},
        fresh:(id:string)=>{
          currentSession.current=id;setSessionId(id);setMessages([]);setQuestion('');setTranscripts([]);
          setCapture(undefined);setAttach(false);setBusy(false);setTab('chat');
          uiTiming.current=new UiAnswerTiming();setUiMetrics({});setMetrics(v=>({...v,latest:{}}));
        },
        reconnect:async()=>{
          reconnectRequested=true;
          await new Promise<void>((resolve,reject)=>{
            const timeout=setTimeout(()=>{eventsConnected.current=undefined;reject(new Error('Контекст очищен, но поток событий не подключился. Прослушивание оставлено выключенным.'));},12000);
            eventsConnected.current=()=>{clearTimeout(timeout);eventsConnected.current=undefined;resolve();};
            setEventsEpoch(v=>v+1);
          });
          contextResetPending.current=false;
        }
      });
      setAudio(result.audio);
      setNotice('Контекст очищен. Начат новый разговор; прежняя история сохранена.');
      if(result.warnings.length)setError(`Контекст очищен. Не удалось возобновить прослушивание: ${result.warnings.join('; ')}`);
      await refreshSessions();
    }catch(e){setError(errorText(e));}
    finally{
      contextResetPending.current=false;eventsConnected.current=undefined;
      if(!reconnectRequested)setEventsEpoch(v=>v+1);
      setSessionLoading(false);setContextClearing(false);
    }
  };
  const toggleAudio=async(source:'loopback'|'microphone')=>{
    if(!api||contextClearing)return;const next=!audio[source];setAudioBusy(source);setError('');
    try{if(!next)await api.json('/audio/stop',{source});else{if(selected[source]===null)throw new Error('Выберите аудиоустройство.');await api.json('/audio/start',{source,device_index:selected[source]});}setAudio(v=>({...v,[source]:next}));setLevels(v=>({...v,[source]:0}));}catch(e){setError(errorText(e));}finally{setAudioBusy('');}
  };
  const doCapture=async()=>{
    if(contextResetPending.current||contextClearing)return;
    if(!api)return;if(!windowId){setError('Сначала выберите окно для снимка.');return;}const ticket=captureGate.current.begin();setCaptureBusy(true);setAttach(false);setCapture(undefined);
    try{const result=await api.json<Capture>('/screen/capture',{window_id:Number(windowId)},ticket.signal);if(ticket.current())setCapture(result);}catch(e){if(ticket.current())setError(errorText(e));}finally{if(ticket.current())setCaptureBusy(false);}
  };captureAction.current=()=>{void doCapture();};
  const save=async()=>{if(!api||!settings)return;setSaving(true);try{const saved=await api.json<Settings>('/settings',settings,undefined,'PUT');setSettings(saved);setNotice('Настройки сохранены. После смены ASR-модели нажмите «Подготовить модели».');}catch(e){setError(errorText(e));}finally{setSaving(false);}};
  const prepare=async()=>{if(!api)return;setWarmup(true);try{const result=await api.json('/models/warmup',{});setNotice(`Подготовка моделей завершена: ${JSON.stringify(result)}`);}catch(e){setError(errorText(e));}finally{setWarmup(false);}};
  const searchKnowledge=async()=>{if(!api)return;setKnowledgeBusy(true);try{setResults(await api.json<Knowledge[]>(`/knowledge/search?q=${encodeURIComponent(search)}`));}catch(e){setError(errorText(e));}finally{setKnowledgeBusy(false);}};
  const importKnowledge=async()=>{if(!api||!importTitle.trim()||!importText.trim())return;setKnowledgeBusy(true);try{await api.json('/knowledge/import',{title:importTitle.trim(),text:importText,as_profile:importProfile});setNotice('Документ добавлен в локальную базу.');setImportTitle('');setImportText('');setImportProfile(false);}catch(e){setError(errorText(e));}finally{setKnowledgeBusy(false);}};
  const field=<K extends keyof Settings>(key:K,value:Settings[K])=>setSettings(s=>s?{...s,[key]:value}:s);
  const latest=metrics.latest??{};
  const gpu=metrics.gpu;
  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">aq</span><div>AQA <strong>Copilot</strong><small>Ваш локальный помощник</small></div></div>
      <button className="new-chat" onClick={()=>void switchSession()}>＋ Новый разговор <kbd>↵</kbd></button>
      <button className="theme-toggle" role="switch" aria-label="Тёмная тема" aria-checked={theme==='dark'} onClick={()=>{const next=theme==='dark'?'light':'dark';applyTheme(next);setTheme(next);}}><span aria-hidden="true">{theme==='dark'?'☾':'☀'}</span><span>Тёмная тема</span><span className={`switch ${theme==='dark'?'on':''}`} aria-hidden="true"/></button>
      <nav aria-label="Главное меню"><button className={tab==='chat'?'nav active':'nav'} onClick={()=>setTab('chat')}>◉ <span>Разговор</span></button><button className={tab==='knowledge'?'nav active':'nav'} onClick={()=>setTab('knowledge')}>▤ <span>База знаний</span></button><button className={tab==='settings'?'nav active':'nav'} onClick={()=>setTab('settings')}>⚙ <span>Настройки</span></button></nav>
      <div className="section-label">ИСТОРИЯ <span>{sessions.length}</span></div>
      <div className="session-list">{sessions.length===0?<p className="muted tiny">Разговоры будут храниться на этом компьютере.</p>:sessions.map(s=><button className={`session ${s.id===sessionId?'selected':''}`} key={s.id} onClick={()=>void switchSession(s.id)}><span>{s.title||'Новый разговор'}</span><small>{s.updated_at?new Date(s.updated_at).toLocaleDateString('ru-RU'):''}</small></button>)}</div>
      <section className="capture-privacy"><label className="check"><input type="checkbox" checked={capturePrivacy===true} disabled={capturePrivacy===null||privacyBusy} onChange={()=>void toggleCapturePrivacy()}/>Скрывать при демонстрации</label><small role="status">{privacyBusy?'Применение…':capturePrivacy===null?'Режим недоступен':capturePrivacy?'Защита включена · значок только в трее':'Защита от захвата выключена'}</small><p>Окно исключается из поддерживаемого захвата; значок панели задач скрыт. Крестик сворачивает в трей. Открыть: клик по значку или Ctrl+Alt+Space. Трей может быть виден на трансляции — проверьте результат со стороны зрителя. Включён при запуске; можно выключить переключателем.</p></section>
      <div className="privacy"><span>◈</span><div>Всё остаётся у вас<small>Локальные модели, аудио и история.<br/>Без облака и телеметрии.</small></div></div>
      <div className="shortcuts"><span>Показать / скрыть <kbd>Ctrl Alt Space</kbd></span><span>Снимок окна <kbd>Ctrl Alt S</kbd></span><span>Остановить <kbd>Ctrl Alt X</kbd></span></div>
    </aside>
    <main>
      <header className="topbar"><div><div className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</div><h1>{tab==='chat'?'Разговор':tab==='knowledge'?'Локальная база знаний':'Настройки'}</h1></div><div className="top-status"><span className={`status-dot ${ready?'online':''}`}/><div>{status}<small>{settings?.model??'Модель не подключена'} · Только на этом ПК</small></div></div></header>
      {error&&<div className="alert error" role="alert"><span>{error}</span><button aria-label="Закрыть ошибку" onClick={()=>setError('')}>×</button></div>}
      {nativeWarnings&&<div className="alert error" role="alert"><span>{nativeWarnings}</span><button aria-label="Закрыть предупреждение приложения" onClick={()=>setNativeWarnings('')}>×</button></div>}
      {notice&&<div className="alert notice" role="status"><span>{notice}</span><button aria-label="Закрыть уведомление" onClick={()=>setNotice('')}>×</button></div>}
      {tab==='chat'?<div className="workspace">
        <section className="conversation">
          <div className="conversation-toolbar"><span><span className={`status-dot ${busy?'working':''}`}/>{!api?'Ожидание локального сервиса':contextClearing?'Очищаю контекст…':busy?'Формирую ответ…':'Готов к вашему вопросу'}</span><div className="conversation-actions"><button className="secondary context-reset-button" disabled={!api||sessionLoading||!!audioBusy} title="Начать без прежней переписки, распознанной речи и снимка. Профиль и база знаний сохраняются." onClick={()=>void clearContext()}>{contextClearing?'Очищаю…':'Очистить контекст'}</button>{sessionId&&<button className="text-button" disabled={sessionLoading} onClick={async()=>{if(!confirm('Удалить историю этого разговора с компьютера?'))return;try{await cancel();await api?.json(`/history?session_id=${encodeURIComponent(sessionId)}`,undefined,undefined,'DELETE');setMessages([]);await refreshSessions();}catch(e){setError(errorText(e));}}}>Очистить историю</button>}</div></div>
          <div className="messages" aria-live="polite">
            {!messages.length?<div className="welcome"><div className="welcome-icon">✳</div><div className="eyebrow">МЕНЬШЕ ПЕРЕКЛЮЧЕНИЙ. БОЛЬШЕ ФОКУСА.</div><h2>Разберём задачу вместе.</h2><p>Задайте вопрос по автоматизации, подключите звук<br/>или добавьте текст из выбранного окна.</p><div className="suggestions">{examples.map(q=><button key={q} onClick={()=>setQuestion(q)}>{q}<span>↗</span></button>)}</div><small className="muted">Ответы строятся локально. Проверяйте предложенный код.</small></div>:messages.map(m=><article className={`message ${m.role==='user'?'user':'assistant'}`} key={m.id}><div className="avatar">{m.role==='user'?'Вы':'aq'}</div><div className="message-body"><div className="message-label">{m.role==='user'?'Вы':'AQA Copilot'}{m.pending&&<span className="streaming">●</span>}</div><div className="message-content">{m.content?(m.role==='assistant'?<FormattedAnswer text={m.content} pending={m.pending}/>:m.content):(!m.pending&&<span className="muted">Ответ не получен.</span>)}</div>{m.pending&&<AnswerProgressView message={m}/>}{m.sources&&m.sources.length>0&&<div className="sources">{m.sources.map(s=><span title={s.path} key={s.path}>▤ {s.title}</span>)}</div>}</div></article>)}<div ref={scroll}/>
          </div>
          <form className="composer" onSubmit={e=>{e.preventDefault();void send();}}>
            {attach&&capture&&<div className="attachment">▧ Текст выбранного окна · {capture.text.length} символов<button type="button" onClick={()=>setAttach(false)}>×</button></div>}
            <textarea aria-label="Ваш вопрос" placeholder="Спросите про тесты, код или текущую задачу…" value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}} rows={3}/>
            <div className="composer-bottom"><span>Enter — отправить · Shift + Enter — новая строка</span><div>{busy&&<button className="stop" type="button" onClick={()=>void cancel()}>■ Стоп</button>}<button className="primary send" type="submit" disabled={!api||!question.trim()||sessionLoading}>Отправить <span>↑</span></button></div></div>
          </form>
          <div className="metric-strip"><span>Запрос → первый токен <strong>{ms(latest.ttft_ms)}</strong></span><span>Запрос → первые слова <strong>{ms(latest.first_words_ms)}</strong></span><span>ASR <strong>{ms(latest.asr_ms)}</strong></span><span>Конец речи → слова <strong>{ms(latest.end_to_first_words_ms)}</strong></span></div>
        </section>
        <aside className="context-panel">
          <div className="panel-title"><h2>Контекст</h2><button className="icon-button" title="Обновить устройства и окна" onClick={()=>void refreshInputs().catch(e=>setError(errorText(e)))}>↻</button></div>
          <section className="context-card"><div className="card-heading"><span>◖ Звук системы</span><button className={`switch ${audio.loopback?'on':''}`} role="switch" aria-label="Звук системы" aria-checked={audio.loopback} disabled={!api||!!audioBusy} onClick={()=>void toggleAudio('loopback')}/></div><p>Слушать собеседника или видео</p><select aria-label="Устройство звука системы" value={selected.loopback??''} disabled={audio.loopback} onChange={e=>setSelected(s=>({...s,loopback:Number(e.target.value)}))}><option value="" disabled>Выберите устройство</option>{devices.loopback.map(d=><option key={d.index} value={d.index}>{d.name}</option>)}</select><Meter value={levels.loopback} active={audio.loopback}/><label className="check tiny"><input type="checkbox" checked={settings?.auto_answer??true} disabled={!settings} onChange={e=>{if(settings)void api?.json<Settings>('/settings',{auto_answer:e.target.checked},undefined,'PUT').then(setSettings).catch(e=>setError(errorText(e)));}}/> Автоответ на речь системы</label></section>
          <section className="context-card"><div className="card-heading"><span>♩ Микрофон</span><button className={`switch ${audio.microphone?'on':''}`} role="switch" aria-label="Микрофон" aria-checked={audio.microphone} disabled={!api||!!audioBusy} onClick={()=>void toggleAudio('microphone')}/></div><p>Отдельный канал вашей речи</p><select aria-label="Устройство микрофона" value={selected.microphone??''} disabled={audio.microphone} onChange={e=>setSelected(s=>({...s,microphone:Number(e.target.value)}))}><option value="" disabled>Выберите устройство</option>{devices.microphone.map(d=><option key={d.index} value={d.index}>{d.name}</option>)}</select><Meter value={levels.microphone} active={audio.microphone}/><small className="muted">{settings?.microphone_auto_answer?'Автоответ включён в настройках':'Только расшифровка, без автоответа'}</small></section>
          <section className="context-card"><div className="card-heading"><span>▧ Выбранное окно</span><span className="badge">OCR</span></div><p>Снимок только по вашему действию</p><select aria-label="Окно для OCR" value={windowId} onChange={e=>{captureGate.current.cancel();setCaptureBusy(false);setWindowId(e.target.value);setCapture(undefined);setAttach(false);}}><option value="">Выберите окно</option>{windows.map(w=><option key={w.id} value={w.id}>{w.title}</option>)}</select><button className="secondary full" disabled={!api||!windowId||captureBusy} onClick={()=>void doCapture()}>{captureBusy?'Распознаю…':'Сделать снимок'}<kbd>Ctrl Alt S</kbd></button>{capture&&<div className="ocr-preview"><img alt="Предпросмотр выбранного окна" src={capture.image_base64.startsWith('data:')?capture.image_base64:`data:image/png;base64,${capture.image_base64}`}/><textarea aria-label="Распознанный текст" value={capture.text} readOnly rows={4}/><small className="muted">{capture.width} × {capture.height} · OCR {ms(capture.ocr_ms)}</small><label className="check"><input type="checkbox" checked={attach} onChange={e=>setAttach(e.target.checked)}/>Добавить текст к следующему вопросу</label></div>}</section>
          {transcripts.length>0&&<section className="transcript-box"><h3>Последняя речь</h3>{transcripts.slice(-3).map((t,i)=><div key={i}><small>{t.source==='microphone'?'Микрофон':'Система'}</small><p>{t.text}</p>{t.raw&&t.raw!==t.text&&<details><summary>Исправлено по словарю · исходная речь</summary><p>{t.raw}</p><button className="text-button" onClick={()=>setQuestion(t.raw!)}>Взять исходный текст ↗</button></details>}<button className="text-button" onClick={()=>setQuestion(t.text)}>В поле вопроса ↗</button></div>)}</section>}
          <div className="gpu-card"><span>◈ {gpu?.name??'Диагностика GPU'}</span><div className="gpu-bar"><i style={{width:`${gpu?.total_mb?Math.min(100,(gpu.used_mb??0)/gpu.total_mb*100):0}%`}}/></div><small>{gpu?.total_mb?`${((gpu.used_mb??0)/1024).toFixed(1)} / ${(gpu.total_mb/1024).toFixed(1)} ГБ VRAM`:'Данные VRAM пока недоступны'}<span>Очередь: −{metrics.queue_dropped??0}</span></small></div>
        </aside>
      </div>:tab==='knowledge'?<div className="page-content"><div className="page-intro"><h2>Ваш опыт — под рукой.</h2><p>Материалы ищутся на этом компьютере и добавляются к ответам с указанием источника.</p></div><form className="search-form" onSubmit={e=>{e.preventDefault();void searchKnowledge();}}><input aria-label="Поиск по базе знаний" placeholder="Например: локаторы, API, стратегия тестирования" value={search} onChange={e=>setSearch(e.target.value)}/><button className="primary" disabled={!api||knowledgeBusy}>Найти</button></form><div className="knowledge-layout"><section><h3>Результаты поиска <span className="badge">{results.length}</span></h3>{results.length===0?<div className="empty-card">Найдите нужную заметку или добавьте свой материал.</div>:results.map(r=><article className="knowledge-result" key={r.path}><h3>{r.title}</h3><small>{r.path}</small><pre>{r.text}</pre></article>)}</section><section className="import-card"><h3>Добавить материал</h3><p className="muted">Markdown или обычный текст. Документ будет храниться локально.</p><label>Название<input value={importTitle} onChange={e=>setImportTitle(e.target.value)} maxLength={200}/></label><label className="check"><input type="checkbox" checked={importProfile} onChange={e=>setImportProfile(e.target.checked)}/>Моё резюме / опыт (заменить профиль)</label><p className="hint">Профиль до 6000 символов используется в вопросах о вашем опыте при включённой базе знаний.</p><label>Текст<textarea value={importText} onChange={e=>setImportText(e.target.value)} rows={12} maxLength={500000}/></label><label className="file-picker">▤ Загрузить .md / .txt<input type="file" accept=".md,.txt,text/plain,text/markdown" onChange={async e=>{const f=e.target.files?.[0];if(!f)return;if(f.size>2_000_000){setError('Файл должен быть не больше 2 МБ.');return;}setImportTitle(f.name.replace(/\.[^.]+$/,''));setImportText(await f.text());}}/></label><button className="primary full" disabled={!api||knowledgeBusy||!importTitle.trim()||!importText.trim()} onClick={()=>void importKnowledge()}>Добавить в базу</button></section></div></div>:<div className="page-content settings-page"><div className="page-intro"><h2>Локально. Под вашим контролем.</h2><p>Адрес модели ограничен loopback. Аудио и снимки не сохраняются по умолчанию.</p></div>{settings?<><section className="settings-card"><h3>Модель ответа</h3><div className="form-grid"><label>Тег Ollama<input value={settings.model} onChange={e=>field('model',e.target.value)}/></label><label>Локальный адрес Ollama<input value={settings.ollama_url} onChange={e=>field('ollama_url',e.target.value)}/></label><label>Контекст, токенов<input type="number" min={512} max={32768} value={settings.num_ctx} onChange={e=>field('num_ctx',Number(e.target.value))}/></label><label>Длина ответа, токенов<input type="number" min={16} max={4096} value={settings.num_predict} onChange={e=>field('num_predict',Number(e.target.value))}/></label><label>Температура<input type="number" min={0} max={2} step={0.1} value={settings.temperature} onChange={e=>field('temperature',Number(e.target.value))}/></label><label>Резерв VRAM, МБ<input type="number" min={0} max={32768} value={settings.vram_reserve_mb} onChange={e=>field('vram_reserve_mb',Number(e.target.value))}/></label></div></section><section className="settings-card"><h3>Распознавание речи и экрана</h3><div className="form-grid"><label className="span-two">Путь к локальной ASR-модели<input value={settings.asr_model_path} onChange={e=>field('asr_model_path',e.target.value)} placeholder="D:/AQA-Copilot-Data/models/faster-whisper-small"/></label><label>Устройство ASR<select value={settings.asr_device} onChange={e=>field('asr_device',e.target.value)}><option value="cuda">GPU / CUDA</option><option value="cpu">CPU</option></select></label><label>Точность ASR<select value={settings.asr_compute_type} onChange={e=>field('asr_compute_type',e.target.value)}>{['int8_float16','float16','int8','float32'].map(v=><option key={v}>{v}</option>)}</select></label><label>Пауза после речи, мс<input type="number" min={160} max={5000} step={20} value={settings.pause_ms} onChange={e=>field('pause_ms',Number(e.target.value))}/></label><label>Путь к Tesseract<input value={settings.tesseract_path} onChange={e=>field('tesseract_path',e.target.value)}/></label></div><p className="hint">После изменения ASR остановите аудио, сохраните настройки и подготовьте модели. Пауза входит в общую задержку ответа.</p></section><section className="settings-card"><h3>Поведение и данные</h3><div className="form-grid"><label>Режим ответа<select value={responseMode(settings)} onChange={e=>setSettings(s=>s?{...s,...responseModeSettings(e.target.value)}:s)}><option value="fast">Быстрый</option><option value="accurate">Точный</option><option value="auto">Авто</option></select></label></div><p className="hint">Быстрый — сразу формирует ответ. Точный — обдумывает каждый вопрос. Авто ускоряет только простые короткие вопросы; для остальных сохраняет обдумывание.</p>{([['online_reference_enabled','Использовать онлайн-справку'],['auto_answer','Автоответ на речь системы'],['microphone_auto_answer','Автоответ на речь микрофона'],['knowledge_enabled','Использовать локальную базу знаний'],['history_enabled','Сохранять историю разговоров']] as const).map(([key,label])=><label className="check" key={key}><input type="checkbox" checked={settings[key]} onChange={e=>field(key,e.target.checked)}/>{label}</label>)}<p className="hint">Онлайн-справка загружает официальную документацию; резюме, история и OCR в сеть не передаются.</p></section><div className="settings-actions"><button className="primary" onClick={()=>void save()} disabled={saving}>{saving?'Сохранение…':'Сохранить настройки'}</button><button className="secondary" onClick={()=>void prepare()} disabled={warmup}>{warmup?'Подготовка моделей…':'Подготовить модели'}</button></div></>:<p>Ожидание настроек локального сервиса…</p>}<section className="settings-card diagnostics"><h3>Диагностика задержки</h3><div className="diagnostic-grid">{[['UI → первый текст (получен)',ms(uiMetrics.first_token_received_ms)],['UI → текст в React',ms(uiMetrics.first_content_commit_ms)],['UI → завершение',ms(uiMetrics.total_ms)],['Запрос → первый токен',ms(latest.ttft_ms)],['Запрос → ≥3 слова',ms(latest.first_words_ms)],['Конец речи → ≥3 слова',ms(latest.end_to_first_words_ms)],['ASR',ms(latest.asr_ms)],['Конец речи',ms(latest.endpoint_ms)],['Полный ответ',ms(latest.total_ms)],['Скорость',typeof latest.tokens_per_second==='number'?`${latest.tokens_per_second.toFixed(1)} ток/с`:'—']].map(([label,value])=><div key={label}><small>{label}</small><strong>{value}</strong></div>)}</div><p className="hint">UI измеряется отдельными часами браузера: ручной запрос — от отправки, автоответ — от события start. «Текст в React» — фиксация обновления, а не измерение пикселей на экране. «Конец речи → слова» включает определение паузы, ASR и генерацию LLM. «Запрос → первые слова» включает подбор контекста, онлайн-справку и генерацию; это момент появления ≥3 слов, а смысл начала требует проверки. Цель 2–3 секунды проверяется по полной задержке после речи.</p><details><summary>Состояние сервиса и моделей</summary><pre>{JSON.stringify({health,metrics,uiMetrics},null,2)}</pre></details></section></div>}
    </main>
  </div>;
}
function Meter({value,active}:{value:number;active:boolean}){return <div className={`meter ${active?'enabled':''}`} role="meter" aria-label="Уровень аудио" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value*100)}>{Array.from({length:30},(_,i)=><i key={i} className={active&&i<value*30?'lit':''}/>)}</div>;}
function AnswerProgressView({message}:{message:Message}){
  const [now,setNow]=useState(()=>performance.now());
  useEffect(()=>{const timer=setInterval(()=>setNow(performance.now()),250);return()=>clearInterval(timer);},[]);
  const progress=describeAnswerProgress(message,now);
  return <div className={`muted ${message.content?'tiny':''}`} role="status" style={{lineHeight:1.7,marginTop:message.content?6:0}}><span>{progress.label} · {progress.seconds} с</span>{progress.notice&&<div className="tiny">{progress.notice}</div>}</div>;
}





