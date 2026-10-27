/* Chrome messaging/WebSocket mocks: no account, network or browser access. */
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const flush = () => new Promise(resolve => setImmediate(resolve));
const root = path.join(__dirname, '../experimental/call-lab-extension');

function background({query, send, savedAuto, setLocal, getTab, clock=setTimeout} = {}) {
  const sockets = [], page = [], stored = [], persisted = [], queries = [], removed = [], timers = new Set();
  let listener;
  const id = 'a'.repeat(32);
  const chrome = {
    runtime: {id, getURL: name => `chrome-extension://${id}/${name}`, onMessage: {addListener: fn => listener = fn}},
    tabs: {
      query: async options => {
        queries.push(options);
        return query ? query(options) : [{id: 42, url: 'https://www.facebook.com/call'}];
      },
      sendMessage: async (tabId, msg) => {
        page.push({tabId, ...msg});
        return send ? send(msg, tabId) : {ok: true, count: 1};
      },
      get: async tabId => getTab ? getTab(tabId) : (await chrome.tabs.query({})).find(tab=>tab.id===tabId),
      remove: async tabId => removed.push(tabId),
      onRemoved: {addListener() {}}, onUpdated: {addListener() {}},
    },
    storage: {session: {set: async data => stored.push(data)}, local: {
      get: async () => ({callAutomation: savedAuto}),
      set: async data => {if(setLocal)await setLocal(data);savedAuto = data.callAutomation; persisted.push(data);},
      setAccessLevel: async () => {},
    }},
  };
  class Socket {
    static OPEN = 1;
    constructor(url) {this.url = url; this.readyState = 0; this.bufferedAmount = 0; this.sent = []; sockets.push(this);}
    open() {this.readyState = 1; this.onopen();}
    send(raw) {this.sent.push(JSON.parse(raw));}
    receive(data) {this.onmessage({data: JSON.stringify(data)});}
    close() {this.readyState = 3; this.onclose?.();}
  }
  const context = vm.createContext({chrome, WebSocket: Socket, URL, crypto: {randomUUID}, setTimeout:clock,
    setInterval: fn => {timers.add(fn); return fn;}, clearInterval: fn => timers.delete(fn)});
  vm.runInContext(fs.readFileSync(path.join(root, 'background.js'), 'utf8'), context);
  const sender = {id, url: chrome.runtime.getURL('popup.html')};
  function popup(action, details = {}) {
    return new Promise(resolve => listener({from: 'call-lab-popup', action, endpoint: 'ws://127.0.0.1:8765', token: 'LOCAL_TEST_TOKEN_123456789', ...details}, sender, resolve));
  }
  function audio(session, details = {}, tabId = 42) {
    listener({from: 'call-lab-content', kind: 'audio', session, data: 'AAAA', sampleRate: 16000, ...details}, {id, tab: {id: tabId}}, () => {});
  }
  function incoming(tabId, ringId='ring-1') {
    return new Promise(resolve => listener({from:'call-lab-content',kind:'incoming',ringId}, {id,tab:{id:tabId,url:'https://www.facebook.com/'}}, resolve));
  }
  function ui(tabId,url='https://www.facebook.com/groupcall/TEST?call_id=one') {
    return new Promise(resolve=>listener({from:'call-lab-content',kind:'call-ui'}, {id,tab:{id:tabId,url}},resolve));
  }
  return {sockets, page, stored, persisted, queries, removed, timers, popup, audio, incoming, ui};
}

test('a call in a separate popup is selected from the Facebook feed and keeps its own audio route', async () => {
  const f = background({
    query: async () => [
      {id: 42, windowId: 1, active: true, url: 'https://www.facebook.com/'},
      {id: 84, windowId: 2, active: false, url: 'https://www.facebook.com/groupcall/ROOM:TEST'},
    ],
    send: async (msg, tabId) => ({ok: true, count: tabId === 84 ? 1 : 0}),
  });
  await f.popup('start'); assert.equal(f.sockets.length, 1);
  assert.ok(Array.isArray(f.queries[0].url));
  assert.equal(f.queries[0].currentWindow, undefined); assert.equal(f.queries[0].active, undefined);
  const ws = f.sockets[0]; ws.open(); ws.receive({type: 'google_ready'}); await flush();
  const started = f.page.find(x => x.command === 'start'); assert.equal(started.tabId, 84);
  const count = ws.sent.length;
  f.audio(started.session, {}, 42); assert.equal(ws.sent.length, count);
  f.audio(started.session, {}, 84); assert.equal(ws.sent.at(-1).type, 'audio');
  ws.receive({type: 'audio', data: 'AAAA', sampleRate: 24000}); await flush();
  assert.equal(f.page.at(-1).tabId, 84);
  await f.popup('stop'); assert.equal(f.page.at(-1).tabId, 84);
});

test('several live calls across windows are refused before relay authentication', async () => {
  const f = background({query: async () => [
    {id: 42, url: 'https://www.facebook.com/call'}, {id: 84, url: 'https://www.messenger.com/call'},
  ]});
  const reply = await f.popup('start');
  assert.match(reply.status, /nhiều cuộc gọi/); assert.equal(f.sockets.length, 0); assert.equal(f.stored.length, 0);
});

test('multiple peer connections in another popup are also ambiguous', async () => {
  const f = background({send: async () => ({ok: true, count: 2})});
  assert.match((await f.popup('start')).status, /nhiều cuộc gọi/);
  assert.equal(f.sockets.length, 0);
});

test('an unrelated page or hostname lookalike is never probed', async () => {
  const f = background({query: async () => [
    {id: 42, url: 'https://www.facebook.com/call'},
    {id: 81, url: 'https://www.facebook.com.attacker.example/'},
    {id: 82, url: 'https://example.com/'},
    {id: 83, url: 'http://www.facebook.com/'},
  ]});
  await f.popup('start'); assert.deepEqual(f.page.map(x => x.tabId), [42]); await f.popup('stop');
});

test('a closed or uninitialized old tab cannot hide a reachable call popup', async () => {
  const f = background({
    query: async () => [{id: 42, url: 'https://www.facebook.com/'}, {id: 84, url: 'https://www.facebook.com/groupcall/test'}],
    send: async (_, tabId) => {if (tabId === 42) throw Error('tab closed'); return {ok: true, count: 1};},
  });
  await f.popup('start'); assert.equal(f.sockets.length, 1);
  const ws = f.sockets[0]; ws.open(); ws.receive({type: 'google_ready'}); await flush();
  assert.equal(f.page.find(x => x.command === 'start').tabId, 84); await f.popup('stop');
});

test('Stop while other windows are being probed prevents a late relay connection', async () => {
  let resolve;
  const f = background({send: () => new Promise(done => resolve = done)});
  const starting = f.popup('start'); await flush();
  await f.popup('stop'); resolve({ok: true, count: 1}); await starting;
  assert.equal(f.sockets.length, 0); assert.equal(f.stored.length, 0);
});

test('missing bridge reports reload instructions without opening Google', async () => {
  const f = background({send: async () => {throw Error('no receiving end');}});
  assert.match((await f.popup('start')).status, /Tải lại Facebook/); assert.equal(f.sockets.length, 0);
});

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

function autoFixture({twoRings=false,handoff=false}={}) {
  let accepted=false;
  const f=background({
    query:async()=>[{id:42,url:'https://www.facebook.com/'},...(accepted||twoRings?[{id:84,url:'https://www.facebook.com/groupcall/test'}]:[])],
    send:async(msg,tabId)=>{
      if(msg.command==='ui-probe')return{ok:true,ended:false,handoff,count:1};
      if(msg.command==='auto-probe')return{ok:true,ringId:!accepted&&(tabId===42||twoRings)?'ring-1':null};
      if(msg.command==='auto-accept'){accepted=true;return{ok:true,accepted:true};}
      if(msg.command==='probe')return{ok:true,count:accepted&&tabId===84?1:0};
      return{ok:true};
    },
  });
  return Object.assign(f,{accepted:()=>accepted});
}

test('automation defaults off and never answers or opens Google without opting in',async()=>{
  const f=autoFixture();await f.incoming(42);assert.equal(f.sockets.length,0);assert.equal(f.accepted(),false);
});

test('automatic call warms Google before accepting and routes audio to the resulting popup',async()=>{
  const f=autoFixture();await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];assert.ok(ws);assert.equal(f.accepted(),false);
  ws.open();assert.equal(f.accepted(),false);ws.receive({type:'google_ready'});
  for(let i=0;i<5;i++)await flush();
  assert.equal(f.accepted(),true);assert.equal(f.page.find(x=>x.command==='start').tabId,84);
  assert.ok(ws.sent.some(x=>x.type==='ready'));
  ws.receive({type:'google_ready'});await flush();assert.equal(f.page.filter(x=>x.command==='auto-accept').length,1);
  await f.popup('stop');assert.ok(f.page.some(x=>x.command==='auto-hangup'&&x.tabId===84));
  assert.equal((await f.popup('status')).autoEnabled,false);
});

test('Google failure leaves the incoming call unaccepted and does not retry the same ring',async()=>{
  const f=autoFixture();await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];ws.open();ws.receive({type:'error',message:'Synthetic failure'});await flush();
  assert.equal(f.accepted(),false);await f.incoming(42);assert.equal(f.sockets.length,1);
  await f.popup('stop');
});

test('Stop during warmup prevents a late Google ready event from answering',async()=>{
  const f=autoFixture();await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];ws.open();await f.popup('stop');ws.receive({type:'google_ready'});await flush();
  assert.equal(f.accepted(),false);assert.equal(ws.readyState,3);
});

test('two incoming windows are refused before Google connection or acceptance',async()=>{
  const f=autoFixture({twoRings:true});await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  assert.equal(f.sockets.length,0);assert.equal(f.accepted(),false);await f.popup('stop');
});

test('persisted opt-in is restored when the service worker starts again',async()=>{
  const f=background({savedAuto:{enabled:true,endpoint:'ws://127.0.0.1:8765',token:'PERSISTED_LOCAL_TOKEN_123456789'}});
  const status=await f.popup('status');assert.equal(status.autoEnabled,true);
  assert.ok(f.page.some(x=>x.command==='auto-watch'&&x.enabled));await f.popup('stop');
});

test('Stop cancels an in-flight persistent opt-in and leaves the saved mode disabled',async()=>{
  let resolve;
  const f=background({setLocal:data=>data.callAutomation.enabled?new Promise(done=>resolve=done):Promise.resolve()});
  const enabling=f.popup('auto',{autoEnabled:true});await flush();
  await f.popup('stop');resolve();await enabling;
  assert.equal((await f.popup('status')).autoEnabled,false);
  assert.equal(f.persisted.at(-1).callAutomation.enabled,false);
  assert.equal(f.sockets.length,0);
});

function cleanupFixture({count=0,ended=true,home=true,getTab,send}={}) {
  const call={id:84,url:'https://www.facebook.com/groupcall/TEST?call_id=one'};
  return background({query:async()=>[...(home?[{id:42,url:'https://www.facebook.com/'}]:[]),call],
    clock:fn=>setImmediate(fn),getTab,
    send:send || (async msg=>msg.command==='ui-probe'?{ok:true,count,ended}:{ok:true,count:0})});
}

test('only a finished disconnected call tab is removed and the Facebook home is kept',async()=>{
  const f=cleanupFixture();await f.ui(84);assert.deepEqual(f.removed,[84]);
  assert.equal(f.sockets.length,0);assert.ok(f.page.every(x=>x.command==='ui-probe'));
});

for(const [note,settings] of [
  ['live peer connection',{count:1}],['no finished UI',{ended:false}],['last Facebook tab',{home:false}],
  ['new call in reused tab',{getTab:async()=>({id:84,url:'https://www.facebook.com/groupcall/TEST?call_id=two'})}],
  ['navigation in progress',{getTab:async()=>({id:84,url:'https://www.facebook.com/groupcall/TEST?call_id=one',pendingUrl:'https://www.facebook.com/'})}],
]) test(`cleanup keeps a tab with ${note}`,async()=>{
  const f=cleanupFixture(settings);await f.ui(84);assert.equal(f.removed.length,0);
});

test('cleanup never treats the feed or an unreachable probe as a finished call',async()=>{
  const f=cleanupFixture();await f.ui(42,'https://www.facebook.com/');assert.equal(f.removed.length,0);assert.equal(f.page.length,0);
  const failed=cleanupFixture({send:async()=>({ok:false})});await failed.ui(84);assert.equal(failed.removed.length,0);
});

test('a peer becoming active during cleanup cancels deletion',async()=>{
  let checks=0;
  const f=cleanupFixture({send:async()=>({ok:true,ended:true,count:checks++===0?0:1})});
  await f.ui(84);assert.equal(f.removed.length,0);
});

test('human takeover stops AI without hanging up or disabling future automatic calls',async()=>{
  const f=autoFixture();await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];ws.open();ws.receive({type:'google_ready'});for(let i=0;i<5;i++)await flush();
  await f.popup('takeover');assert.equal(ws.readyState,3);
  assert.equal((await f.popup('status')).autoEnabled,true);
  assert.ok(!f.page.some(x=>x.command==='auto-hangup'));assert.equal(f.removed.length,0);
  await f.popup('stop');
});

test('a peer ended event cannot hang up a later call on the same page',async()=>{
  const f=autoFixture();await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];ws.open();ws.receive({type:'google_ready'});for(let i=0;i<5;i++)await flush();
  const session=f.page.find(x=>x.command==='start').session;
  f.audio(session,{kind:'ended'},84);await flush();
  assert.ok(!f.page.some(x=>x.command==='auto-hangup'));assert.equal(ws.readyState,3);await f.popup('stop');
});

test('a new incoming or manual start cannot replace the active AI call',async()=>{
  const f=autoFixture();await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];ws.open();ws.receive({type:'google_ready'});for(let i=0;i<5;i++)await flush();
  await f.incoming(42,'ring-2');assert.equal((await f.popup('start')).ok,false);
  assert.equal(f.sockets.length,1);assert.equal(ws.readyState,1);await f.popup('stop');
});

test('an explicit another-device notice triggers handover without hanging up',async()=>{
  const f=autoFixture({handoff:true});await f.popup('auto',{autoEnabled:true});await f.incoming(42);
  const ws=f.sockets[0];ws.open();ws.receive({type:'google_ready'});for(let i=0;i<5;i++)await flush();
  await f.ui(84,'https://www.facebook.com/groupcall/test');assert.equal(ws.readyState,3);
  assert.equal((await f.popup('status')).autoEnabled,true);assert.ok(!f.page.some(x=>x.command==='auto-hangup'));
  await f.popup('stop');
});

test('another-device notice from an old call cannot stop a new call in the same tab',async()=>{
  const f=background({query:async()=>[{id:42,url:'https://www.facebook.com/groupcall/TEST?call_id=new'}],
    send:async msg=>msg.command==='ui-probe'?{ok:true,ended:true,handoff:true,count:0}:{ok:true,count:1}});
  await f.popup('start');const ws=f.sockets[0];ws.open();ws.receive({type:'google_ready'});await flush();
  await f.ui(42,'https://www.facebook.com/groupcall/TEST?call_id=old');assert.equal(ws.readyState,1);
  await f.popup('stop');
});
