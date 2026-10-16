export async function* readSSE(stream, signal) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let fields = [];
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', abort, {once:true});
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Request cancelled', 'AbortError');
      const {value, done} = await reader.read();
      if (signal?.aborted) throw new DOMException('Request cancelled', 'AbortError');
      pending += decoder.decode(value, {stream:!done});
      if (done && pending && !pending.endsWith('\n')) pending += '\n';
      let newline;
      while ((newline = pending.indexOf('\n')) !== -1) {
        const line = pending.slice(0, newline).replace(/\r$/, '');
        pending = pending.slice(newline + 1);
        if (!line) {
          if (fields.length) { yield JSON.parse(fields.join('\n')); fields = []; }
        } else if (line.startsWith('data:')) fields.push(line.slice(5).replace(/^ /, ''));
      }
      if (done) { if (fields.length) yield JSON.parse(fields.join('\n')); break; }
    }
  } finally {
    signal?.removeEventListener('abort', abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
export class RequestGate {
  controller;
  generation = 0;
  begin() {
    this.cancel();
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    return {signal:controller.signal, current:() => this.generation === generation && !controller.signal.aborted};
  }
  cancel() { this.generation++; this.controller?.abort(); this.controller = undefined; }
}
export class CancelBarrier {
  pending = Promise.resolve();
  run(action) {
    const operation = this.pending.then(action);
    this.pending = operation.catch(() => {});
    return operation;
  }
  settled() { return this.pending; }
}
export class ResponseTracker {
  active;
  ignored = new Set();
  start(id) { if (this.active && this.active !== id) this.ignored.add(this.active); this.active = id; }
  accepts(id) { return !this.ignored.has(id); }
  finish(id) { if (this.active !== id) return false; this.active = undefined; return true; }
  cancel() { if (this.active) this.ignored.add(this.active); this.active = undefined; }
}
