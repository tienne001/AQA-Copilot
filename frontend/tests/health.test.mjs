import test from 'node:test';
import assert from 'node:assert/strict';
import {describeHealth} from '../src/health.mjs';
test('API online never implies models ready while cold warmup is running', () => {
  assert.deepEqual(describeHealth({ready:true,warming_up:true,asr:{loaded:true},ollama:{available:true,installed:true}}),{ready:false,status:'Модели загружаются…'});
});
test('missing ASR remains a preparation state even with installed Ollama model', () => {
  assert.equal(describeHealth({ready:true,asr:{loaded:false},ollama:{available:true,installed:true}}).ready,false);
  assert.equal(describeHealth({ready:true,asr:{loaded:false},ollama:{available:true,installed:true}}).status,'Модели загружаются…');
});
test('ready status requires loaded ASR and available installed local model', () => {
  assert.deepEqual(describeHealth({ready:true,warming_up:false,asr:{loaded:true},ollama:{available:true,installed:true}}),{ready:true,status:'Локальные модели готовы'});
});
test('warmup errors remain visible instead of green ready state', () => {
  const result=describeHealth({ready:true,warmup_errors:['CUDA memory'],asr:{loaded:true},ollama:{available:true,installed:true}});
  assert.equal(result.ready,false);assert.match(result.status,/Ошибка подготовки/);
});
