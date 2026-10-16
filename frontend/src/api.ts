import { invoke } from '@tauri-apps/api/core';
import { readSSE } from './stream.mjs';

export type Connection = {url:string;token:string};
export type AnswerProgress = {stage:string;label:string;elapsed_ms:number};
export type Event = {type:string;request_id?:string;session_id?:string;text?:string;raw_text?:string;corrections?:{from:string;to:string}[];error?:string;source?:string;level?:number;stage?:string;label?:string;elapsed_ms?:number;metrics?:Metrics['latest'];sources?:{title:string;path:string}[];[key:string]:unknown};
export type Device = {index:number;name:string;rate:number;channels:number};
export type Devices = {loopback:Device[];microphone:Device[];default_loopback:number|null;default_microphone:number|null};
export type Settings = {model:string;ollama_url:string;asr_model_path:string;asr_device:string;asr_compute_type:string;pause_ms:number;temperature:number;num_ctx:number;num_predict:number;reasoning_enabled:boolean;adaptive_reasoning:boolean;online_reference_enabled:boolean;auto_answer:boolean;microphone_auto_answer:boolean;knowledge_enabled:boolean;history_enabled:boolean;vram_reserve_mb:number;tesseract_path:string};
export type Metrics = {gpu?:{name?:string;total_mb?:number;used_mb?:number;free_mb?:number};latest?:{ttft_ms?:number;first_words_ms?:number;end_to_first_words_ms?:number;total_ms?:number;tokens_per_second?:number;asr_ms?:number;endpoint_ms?:number;[key:string]:unknown};audio?:{loopback:boolean;microphone:boolean};queue_dropped?:number;[key:string]:unknown};
export type WindowItem = {id:number;title:string;process:string};
export type Capture = {image_base64:string;width:number;height:number;text:string;ocr_ms:number;capture_ms:number;language:string};
export type Session = {id:string;title:string;updated_at:string};
export type Message = {id:string;role:string;content:string;created_at?:string;request_id?:string;sources?:{title:string;path:string}[];pending?:boolean;progress?:AnswerProgress};
export type Knowledge = {title:string;text:string;path:string;score:number};
export async function connectionInfo():Promise<Connection> {
  if ('__TAURI_INTERNALS__' in window) return invoke('connection_info');
  if (!import.meta.env.DEV) throw new Error('Откройте AQA Copilot через установленное приложение: подключение создаётся локальным процессом.');
  const url = import.meta.env.VITE_API_URL;
  const token = import.meta.env.VITE_API_TOKEN;
  if (!url || !token) throw new Error('Сервис не подключён. Запустите приложение или задайте VITE_API_URL и VITE_API_TOKEN для режима разработки.');
  const parsed = new URL(url);
  if (parsed.protocol !== 'http:' || !['127.0.0.1','[::1]'].includes(parsed.hostname)) throw new Error('Допустим только локальный адрес сервиса.');
  return {url:url.replace(/\/$/,''),token};
}
export class Api {
  constructor(public connection:Connection) {}
  async response(path:string, body?:unknown, signal?:AbortSignal, method?:string) {
    const response = await fetch(this.connection.url + path, {method:method ?? (body === undefined ? 'GET':'POST'),headers:{Authorization:`Bearer ${this.connection.token}`,...(body === undefined ? {}:{'Content-Type':'application/json'})},body:body === undefined ? undefined:JSON.stringify(body),signal});
    if (!response.ok) {
      const error = await response.json().catch(() => ({detail:response.statusText}));
      throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
    }
    return response;
  }
  async json<T>(path:string,body?:unknown,signal?:AbortSignal,method?:string):Promise<T> {return (await this.response(path,body,signal,method)).json();}
  async *events(path:string,body?:unknown,signal?:AbortSignal):AsyncGenerator<Event> {
    const response = await this.response(path,body,signal);
    if (!response.body) throw new Error('Пустой поток ответа сервиса.');
    for await (const event of readSSE(response.body, signal)) yield event as Event;
  }
}
