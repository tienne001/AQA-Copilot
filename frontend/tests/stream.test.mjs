import test from 'node:test';
import assert from 'node:assert/strict';
import {readSSE, RequestGate, CancelBarrier, ResponseTracker} from '../src/stream.mjs';

function bytes(parts) {
  return new ReadableStream({start(c) { for (const part of parts) c.enqueue(part); c.close(); }});
}
test('SSE retains Cyrillic UTF8 split across network chunks and CRLF records', async () => {
  const wire = new TextEncoder().encode(': heartbeat\r\ndata: {"type":"token","text":"Привет"}\r\n\r\ndata: {"type":"done"}\n\n');
  const result = [];
  for await (const event of readSSE(bytes([wire.slice(0, 50), wire.slice(50,51), wire.slice(51)]))) result.push(event);
  assert.deepEqual(result, [{type:'token',text:'Привет'},{type:'done'}]);
});
test('SSE decodes a final event without trailing blank line and ignores heartbeat', async () => {
  const result = [];
  for await (const event of readSSE(bytes([new TextEncoder().encode(': ping\n\ndata: {"type":"done"}')]))) result.push(event);
  assert.deepEqual(result, [{type:'done'}]);
});
test('SSE abort releases and cancels a pending reader', async () => {
  let cancelled = false;
  const source = new ReadableStream({cancel(){cancelled = true;}});
  const controller = new AbortController();
  const pending = (async () => {for await (const _ of readSSE(source, controller.signal)) {}})();
  controller.abort();
  await assert.rejects(pending, {name:'AbortError'});
  assert.equal(cancelled, true);
});
test('malformed nonempty SSE data surfaces protocol failure', async () => {
  await assert.rejects(async () => {for await(const _ of readSSE(bytes([new TextEncoder().encode('data: broken\n\n')]))) {}}, /JSON|Unexpected|protocol/i);
});
test('new request cancels a pending header request and rejects stale tokens', () => {
  const gate = new RequestGate();
  const first = gate.begin();
  const second = gate.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(first.current(), false);
  assert.equal(second.signal.aborted, false);
  assert.equal(second.current(), true);
  gate.cancel();
  assert.equal(second.signal.aborted, true);
  assert.equal(second.current(), false);
});
test('a new answer waits for pending global cancel so it cannot cancel the new answer', async () => {
  const barrier = new CancelBarrier();
  let finish;
  const cancellation = new Promise(resolve => {finish=resolve;});
  barrier.run(() => cancellation);
  let ready = false;
  const wait = barrier.settled().then(() => {ready = true;});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ready, false);
  finish(); await wait;
  assert.equal(ready, true);
});
test('cancel failures are surfaced but do not block subsequent answers', async () => {
  const barrier = new CancelBarrier();
  await assert.rejects(barrier.run(() => Promise.reject(new Error('service offline'))), /service offline/);
  await barrier.settled();
});
test('a superseded cancelled event cannot clear a newer answer busy state', () => {
  const tracker = new ResponseTracker();
  tracker.start('old');tracker.start('new');
  assert.equal(tracker.finish('old'),false);
  assert.equal(tracker.finish('new'),true);
  assert.equal(tracker.finish('new'),false);
});
test('tokens of a cancelled or superseded automatic answer are rejected', () => {
  const tracker = new ResponseTracker();
  tracker.start('old');tracker.start('new');
  assert.equal(tracker.accepts('old'),false);
  assert.equal(tracker.accepts('new'),true);
  tracker.cancel();
  assert.equal(tracker.accepts('new'),false);
});
