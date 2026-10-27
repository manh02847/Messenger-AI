/* Chrome messaging/WebSocket mocks: no account, network or browser access. */
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const flush = () => new Promise(resolve => setImmediate(resolve));
const root = path.join(__dirname, '../experimental/call-lab-extension');

function background({query, send} = {}) {
  const sockets = [], page = [], stored = [], timers = new Set();
  let listener;
  const id = 'a'.repeat(32);
  const chrome = {
    runtime: {id, getURL: name => `chrome-extension://${id}/${name}`, onMessage: {addListener: fn => listener = fn}},
    tabs: {
      query: query || (async () => [{id: 42, url: 'https://www.facebook.com/call'}]),
      sendMessage: async (tabId, msg) => {
        page.push({tabId, ...msg});
        return send ? send(msg) : {ok: true, count: 1};
      },
      onRemoved: {addListener() {}}, onUpdated: {addListener() {}},
    },
    storage: {session: {set: async data => stored.push(data)}},
  };
  class Socket {
    static OPEN = 1;
    constructor(url) {this.url = url; this.readyState = 0; this.bufferedAmount = 0; this.sent = []; sockets.push(this);}
    open() {this.readyState = 1; this.onopen();}
    send(raw) {this.sent.push(JSON.parse(raw));}
    receive(data) {this.onmessage({data: JSON.stringify(data)});}
    close() {this.readyState = 3; this.onclose?.();}
  }
  const context = vm.createContext({chrome, WebSocket: Socket, URL, crypto: {randomUUID},
    setInterval: fn => {timers.add(fn); return fn;}, clearInterval: fn => timers.delete(fn)});
  vm.runInContext(fs.readFileSync(path.join(root, 'background.js'), 'utf8'), context);
  const sender = {id, url: chrome.runtime.getURL('popup.html')};
  function popup(action, details = {}) {
    return new Promise(resolve => listener({from: 'call-lab-popup', action, endpoint: 'ws://127.0.0.1:8765', token: 'LOCAL_TEST_TOKEN_123456789', ...details}, sender, resolve));
  }
  function audio(session, details = {}) {
    listener({from: 'call-lab-content', kind: 'audio', session, data: 'AAAA', sampleRate: 16000, ...details}, {id, tab: {id: 42}}, () => {});
  }
  return {sockets, page, stored, timers, popup, audio};
}

test('no call or invalid relay never opens a WebSocket or stores a token', async () => {
  const f = background({send: async () => ({ok: true, count: 0})});
  await f.popup('start'); assert.equal(f.sockets.length, 0); assert.equal(f.stored.length, 0);
  assert.equal((await f.popup('start', {endpoint: 'ws://external.example/'})).ok, false);
  assert.equal((await f.popup('start', {endpoint: 'ws://127.0.0.1:8765/?token=bad'})).ok, false);
  assert.equal(f.sockets.length, 0);
});

test('audio is gated by Google and page readiness; Stop closes both sides', async () => {
  const f = background(); await f.popup('start'); const ws = f.sockets[0]; ws.open();
  const auth = ws.sent[0]; assert.equal(auth.type, 'auth');
  const session = f.page.find(x => x.command === 'probe').session;
  f.audio(session); assert.equal(ws.sent.length, 1);
  ws.receive({type: 'google_ready'}); await flush();
  assert.ok(ws.sent.some(x => x.type === 'ready'));
  f.audio(session); assert.equal(ws.sent.at(-1).type, 'audio');
  ws.receive({type: 'audio', data: 'AAAA', sampleRate: 24000}); await flush();
  assert.equal(f.page.at(-1).command, 'audio');
  assert.ok(!JSON.stringify(f.page).includes(auth.token), 'relay token must never reach the page');
  await f.popup('stop');
  assert.equal(ws.readyState, 3); assert.equal(f.page.at(-1).command, 'stop'); assert.equal(f.timers.size, 0);
  const count = ws.sent.length; f.audio(session); assert.equal(ws.sent.length, count);
});

test('double Start is refused and Stop cancels an outstanding tab lookup', async () => {
  let resolve;
  const f = background({query: () => new Promise(done => resolve = done)});
  const first = f.popup('start');
  assert.equal((await f.popup('start')).ok, false);
  await f.popup('stop'); resolve([{id: 42, url: 'https://www.facebook.com/call'}]);
  await first; assert.equal(f.sockets.length, 0); assert.equal(f.stored.length, 0);
});

test('a late failure from an old session cannot stop the next call', async () => {
  let rejectOld; let starts = 0;
  const f = background({send: msg => {
    if (msg.command === 'start' && ++starts === 1) return new Promise((_, reject) => rejectOld = reject);
    return {ok: true, count: 1};
  }});
  await f.popup('start'); const old = f.sockets[0]; old.open(); old.receive({type: 'google_ready'}); await flush();
  await f.popup('stop'); await f.popup('start'); const current = f.sockets[1]; current.open(); current.receive({type: 'google_ready'}); await flush();
  rejectOld(Error('old tab failed')); await flush();
  assert.equal(current.readyState, 1); assert.equal((await f.popup('status')).active, true);
  await f.popup('stop');
});

test('upstream disconnect or audio backlog restores the page microphone', async () => {
  const f = background(); await f.popup('start'); let ws = f.sockets[0]; ws.open(); ws.receive({type: 'google_ready'}); await flush();
  ws.close(); await flush(); assert.equal(f.page.at(-1).command, 'stop'); assert.equal((await f.popup('status')).active, false);
  await f.popup('start'); ws = f.sockets[1]; ws.open(); ws.receive({type: 'google_ready'}); await flush();
  ws.bufferedAmount = 128001; f.audio(f.page.findLast(x => x.command === 'start').session); await flush();
  assert.equal(ws.readyState, 3); assert.equal(f.page.at(-1).command, 'stop');
});

test('late Stop acknowledgement in content script does not clear a newer session', async () => {
  const id = 'b'.repeat(32), events = [], forwarded = [], listeners = [];
  let runtime;
  const window = {postMessage: msg => events.push(msg), addEventListener: (_, fn) => listeners.push(fn)};
  const chrome = {runtime: {id, onMessage: {addListener: fn => runtime = fn}, sendMessage: async msg => forwarded.push(msg)}};
  vm.runInContext(fs.readFileSync(path.join(root, 'content.js'), 'utf8'), vm.createContext({window, chrome, crypto: {randomUUID}, location: {origin: 'https://www.facebook.com'}, setTimeout, clearTimeout}));
  const command = (name, session) => new Promise(resolve => runtime({to: 'call-lab-content', command: name, session}, {id}, resolve));
  function reply(msg) {for (const listener of listeners) listener({source: window, data: {channel: msg.channel, direction: 'event', kind: 'reply', requestId: msg.requestId, ok: true}});}
  let pending = command('start', 'old'); reply(events.at(-1)); await pending;
  const stopping = command('stop', 'old'); const oldStop = events.at(-1);
  pending = command('start', 'new'); reply(events.at(-1)); await pending;
  reply(oldStop); await stopping;
  for (const listener of listeners) listener({source: window, data: {channel: oldStop.channel, direction: 'event', kind: 'audio', session: 'new', data: 'AAAA', sampleRate: 16000}});
  await flush(); assert.equal(forwarded.at(-1).session, 'new');
});
