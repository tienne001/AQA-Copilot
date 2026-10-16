import {RequestGate,ResponseTracker} from './stream.mjs';
export class ConversationFlow {
  requests = new RequestGate();
  responses = new ResponseTracker();
  manualIds = new Set();
  started = new Set();
  pendingId;
  beginManual() {
    this.responses.cancel();
    const ticket=this.requests.begin();
    this.pendingId=`pending:${this.requests.generation}`;
    return {...ticket,pendingId:this.pendingId};
  }
  route(event,origin,ticket) {
    const rejected={accepted:false,showQuestion:false,finished:false,pendingId:undefined};
    const id=event.request_id;
    if(origin==='manual'){
      if(id)this.manualIds.add(id);
      if(ticket&&!ticket.current())return rejected;
    }else if(id&&this.manualIds.has(id))return rejected;
    if(id&&!this.responses.accepts(id))return rejected;
    if(event.type==='start'&&id){
      if(this.started.has(id))return rejected;
      this.started.add(id);
      // A server auto-answer can supersede a manual fetch before its finally executes.
      // Invalidate that fetch's ownership before publishing the new pending answer.
      if(origin==='auto')this.requests.cancel();
      this.responses.start(id);
      const pendingId=this.pendingId;this.pendingId=undefined;
      return {accepted:true,showQuestion:origin==='auto',finished:false,pendingId};
    }
    const terminal=['done','error','cancelled'].includes(event.type);
    // Heartbeats and trailing stream events cannot take ownership or revive a
    // completed answer, including a duplicate delivered by the other SSE feed.
    if((event.type==='progress'||event.type==='token'||(terminal&&id))&&(!id||id!==this.responses.active))return rejected;
    return {accepted:true,showQuestion:false,finished:Boolean(id&&terminal&&this.responses.finish(id)),pendingId:undefined};
  }
  finishManual(ticket) {
    if(!ticket.current())return false;
    this.cancel();return true;
  }
  cancel() { this.requests.cancel();this.responses.cancel(); }
}
export function applyAnswerEvent(messages,event,showQuestion,clientNow=performance.now()) {
  if(event.type==='start'){
    const pending=showQuestion?undefined:messages.find(message=>message.id===event.pending_id&&message.pending);
    return [
    ...messages.filter(message=>message.id!==event.pending_id).map(message=>({...message,pending:false})),
    ...(showQuestion&&event.question?[{id:`${event.request_id}:question`,role:'user',content:String(event.question)}]:[]),
    {id:pending?.id??event.request_id,request_id:event.request_id,role:'assistant',content:'',pending:true,
      client_started_at:pending?.client_started_at??clientNow,
      progress:{stage:'context',label:'Подготовка ответа',elapsed_ms:0}}
    ];
  }
  if(event.type==='progress')return messages.map(message=>{
    if(message.request_id!==event.request_id||!message.pending)return message;
    const previous=message.progress??{stage:'context',label:'Подготовка ответа',elapsed_ms:0};
    const elapsed=Number.isFinite(event.elapsed_ms)&&event.elapsed_ms>=0?event.elapsed_ms:previous.elapsed_ms;
    // Never move the clock or stage backwards when a delayed heartbeat arrives.
    if(elapsed<previous.elapsed_ms)return message;
    return {...message,progress:{
      stage:typeof event.stage==='string'?event.stage:previous.stage,
      label:typeof event.label==='string'&&event.label.trim()?event.label:previous.label,
      elapsed_ms:elapsed
    }};
  });
  if(event.type==='token')return messages.map(message=>message.request_id===event.request_id&&message.pending?{...message,content:message.content+(event.text??'')}:message);
  if(['done','error','cancelled'].includes(event.type))return messages.map(message=>message.request_id===event.request_id?{...message,pending:false,sources:event.sources??message.sources}:message);
  return messages;
}
export function describeAnswerProgress(message,clientNow) {
  const progress=message.progress;
  // Pending rows carry a browser timestamp from submission (or auto start).
  // Never combine its epoch with a Python timestamp or reset it at SSE headers.
  const elapsed=Number.isFinite(clientNow)&&Number.isFinite(message.client_started_at)
    ?Math.max(0,clientNow-message.client_started_at)
    :Number.isFinite(progress?.elapsed_ms)?Math.max(0,progress.elapsed_ms):0;
  return {
    label:progress?.label||'Подготовка ответа',
    seconds:Math.floor(elapsed/1000),
    notice:elapsed>=12000?'Ответ занимает больше обычного. Работа продолжается.':elapsed>=3000&&!message.content?'Подготовка ответа продолжается.':''
  };
}
export function responseMode(settings) {
  return !settings.reasoning_enabled?'fast':settings.adaptive_reasoning?'auto':'accurate';
}
export function responseModeSettings(mode) {
  return {reasoning_enabled:mode!=='fast',adaptive_reasoning:mode==='auto'};
}

// UI timings use only the browser clock; never subtract Python timestamps.
export class UiAnswerTiming {
  constructor(now=()=>performance.now()) { this.now=now;this.current=undefined; }
  begin(id,origin='manual') {
    this.current={request_id:id,origin,started:this.now(),outcome:'pending',
      first_event_ms:null,first_token_received_ms:null,first_content_commit_ms:null,total_ms:null};
  }
  receive(event,pendingId,origin) {
    if(event.type==='start') {
      if(origin!=='auto'&&this.current?.request_id===pendingId)this.current.request_id=event.request_id;
      else this.begin(event.request_id,'auto');
    }
    const c=this.current;
    if(!c||c.request_id!==event.request_id)return;
    const elapsed=this.now()-c.started;
    if(c.first_event_ms===null)c.first_event_ms=elapsed;
    if(event.type==='token'&&event.text&&c.first_token_received_ms===null)c.first_token_received_ms=elapsed;
    if(['done','error','cancelled'].includes(event.type)){c.outcome=event.type;c.total_ms=elapsed;}
  }
  commit(id) {
    const c=this.current;
    if(!c||c.request_id!==id||c.first_content_commit_ms!==null)return false;
    c.first_content_commit_ms=this.now()-c.started;return true;
  }
  finish(outcome) {
    if(this.current?.outcome==='pending'){
      this.current.outcome=outcome;this.current.total_ms=this.now()-this.current.started;
    }
  }
  snapshot() { if(!this.current)return {};const {started,...metrics}=this.current;return metrics; }
}
export function beginPendingAnswer(messages,id,question,clientNow=performance.now()) {
  return [...messages.map(message=>({...message,pending:false})),
    {id:`${id}:question`,role:'user',content:question},
    {id,role:'assistant',content:'',pending:true,client_started_at:clientNow,progress:{stage:'connecting',label:'Отправляю вопрос',elapsed_ms:0}}];
}

export function mergeMetricsSnapshot(current,incoming,expectedId) {
  const latest=incoming.latest;
  const stale=expectedId&&latest?.request_id!==expectedId;
  const regressed=current.latest?.request_id===latest?.request_id&&
    current.latest?.outcome!=='pending'&&latest?.outcome==='pending';
  return {...current,...incoming,...(stale||regressed?{latest:current.latest}:{})};
}
