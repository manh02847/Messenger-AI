/* Public synthetic media only; these tests don't claim to replace Chromium. */
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function fixture({deferResume=false,deferRestore=false}={}) {
  const events=[], listeners=[], contexts=[];
  let resume, restore;
  const window={postMessage(data){queueMicrotask(()=>{events.push(data);for(const fn of listeners)void fn({source:window,data});});},addEventListener(type,fn){if(type==='message')listeners.push(fn);}};
  class PC {
    constructor(){
      this.connectionState='connected';this.handlers={};
      this.original={kind:'audio',id:'physical-microphone',readyState:'live'};
      this.peer={kind:'audio',id:'caller-audio',readyState:'live'};
      this.sender={track:this.original,replaceTrack:async track=>{if(deferRestore&&track===this.original&&this.sender.track!==track){deferRestore=false;await new Promise(resolve=>restore=resolve);}this.sender.track=track;}};
    }
    getSenders(){return[this.sender];}getReceivers(){return[{track:this.peer}];}
    addEventListener(type,fn){this.handlers[type]=fn;}
    close(){this.connectionState='closed';this.handlers.connectionstatechange();}
  }
  window.RTCPeerConnection=PC;
  class Stream{constructor(tracks){this.tracks=tracks;}getTracks(){return this.tracks;}getAudioTracks(){return this.tracks;}}
  class Node{connect(other){return other;}disconnect(){this.disconnected=true;}}
  class Context {
    constructor(){this.currentTime=10;this.sampleRate=48000;this.state='suspended';this.destination=new Node();this.sources=[];contexts.push(this);}
    async resume(){if(deferResume)await new Promise(resolve=>resume=resolve);if(this.state==='closed')throw Error('Context closed');this.state='running';}
    createMediaStreamDestination(){const node=new Node();node.stream=new Stream([{kind:'audio',id:'ai-audio',readyState:'live',stop(){this.readyState='ended';}}]);return node;}
    createMediaStreamSource(stream){this.input=stream.getTracks()[0].id;return new Node();}
    createScriptProcessor(){this.processor=new Node();return this.processor;}
    createGain(){const node=new Node();node.gain={value:1};return node;}
    createBuffer(channels,length,sampleRate){const data=new Float32Array(length);return{duration:length/sampleRate,getChannelData:()=>data};}
    createBufferSource(){const source=new Node();source.start=time=>source.started=time;source.stop=()=>source.stopped=true;this.sources.push(source);return source;}
    async close(){this.state='closed';}
  }
  const context=vm.createContext({window,location:{origin:'https://www.facebook.com'},AudioContext:Context,MediaStream:Stream,Float32Array,Uint8Array,DataView,Math,btoa,atob,queueMicrotask,console});
  const root=path.join(__dirname,'../experimental/call-lab-extension');
  vm.runInContext(fs.readFileSync(path.join(root,'pcm.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'bridge-main.js'),'utf8'),context);
  let count=0;
  async function send(command,details={},session='test-session'){
    const requestId=String(++count);
    window.postMessage({channel:'messenger-ai-call-lab-v1',direction:'command',requestId,session,command,...details});
    for(let i=0;i<100;i++){
      const reply=events.find(x=>x.kind==='reply'&&x.requestId===requestId);
      if(reply)return reply;
      await new Promise(resolve=>setTimeout(resolve,1));
    }
    throw Error('No bridge response');
  }
  return{window,events,contexts,send,resume:()=>resume?.(),restore:()=>restore?.(),isRestoring:()=>!!restore,pcm:context.CallLabPCM};
}

test('observer is passive and refuses absent/ambiguous calls',async()=>{
  const f=fixture();
  assert.equal((await f.send('probe')).count,0);
  assert.equal((await f.send('start')).code,'NO_CALL');
  const one=new f.window.RTCPeerConnection();
  assert.equal(one.sender.track,one.original);
  assert.equal(f.contexts.length,0);
  new f.window.RTCPeerConnection();
  assert.equal((await f.send('start')).code,'MULTIPLE_CALLS');
  assert.equal(one.sender.track,one.original);
});

test('only caller audio is captured and microphone is restored after Stop',async()=>{
  const f=fixture(),pc=new f.window.RTCPeerConnection();
  assert.equal((await f.send('start')).ok,true);
  assert.equal(pc.sender.track.id,'ai-audio');
  const ctx=f.contexts[0];assert.equal(ctx.input,'caller-audio');
  ctx.processor.onaudioprocess({inputBuffer:{getChannelData:()=>Float32Array.from({length:4096},(_,i)=>.5*Math.sin(2*Math.PI*440*i/48000))}});
  await new Promise(resolve=>setImmediate(resolve));
  const audio=f.events.filter(x=>x.kind==='audio');assert.ok(audio.length);
  assert.equal(audio[0].sampleRate,16000);
  assert.ok(audio.every(x=>Buffer.from(x.data,'base64').length<=3200));
  assert.equal((await f.send('stop')).ok,true);
  assert.equal(pc.sender.track,pc.original);assert.equal(ctx.state,'closed');
  assert.equal(ctx.processor.onaudioprocess,null);
});

test('interruption clears queued audio and stale sessions cannot play or stop a new call',async()=>{
  const f=fixture(),pc=new f.window.RTCPeerConnection();await f.send('start');
  const data=Buffer.alloc(48000).toString('base64');
  await f.send('audio',{data});await f.send('audio',{data});
  const ctx=f.contexts[0];assert.equal(ctx.sources.length,2);
  await f.send('clear');assert.ok(ctx.sources.every(x=>x.stopped));
  await f.send('audio',{data});assert.ok(ctx.sources[2].started<10.1);
  await f.send('stop');await f.send('start',{},'new-session');
  await f.send('stop',{},'test-session');assert.equal(pc.sender.track.id,'ai-audio');
  await f.send('stop',{},'new-session');assert.equal(pc.sender.track,pc.original);
});

test('hanging up closes the audio graph and signals the relay',async()=>{
  const f=fixture(),pc=new f.window.RTCPeerConnection();await f.send('start');pc.close();
  for(let i=0;i<10&&!f.events.some(x=>x.kind==='ended');i++)await new Promise(r=>setTimeout(r,1));
  assert.ok(f.events.some(x=>x.kind==='ended'));
  assert.equal(f.contexts[0].state,'closed');assert.equal(pc.sender.track,pc.original);
});

test('Stop during audio initialization cancels the pending replacement',async()=>{
  const f=fixture({deferResume:true}),pc=new f.window.RTCPeerConnection();
  const starting=f.send('start');
  for(let i=0;i<20&&!f.contexts.length;i++)await new Promise(r=>setTimeout(r,1));
  assert.equal((await f.send('stop')).ok,true);
  f.resume();assert.equal((await starting).code,'CANCELLED');
  assert.equal(pc.sender.track,pc.original);assert.equal(f.contexts[0].state,'closed');
});

test('a new Start waits for the old physical microphone restoration',async()=>{
  const f=fixture({deferRestore:true}),pc=new f.window.RTCPeerConnection();await f.send('start');
  const stopping=f.send('stop');
  for(let i=0;i<20&&!f.isRestoring();i++)await new Promise(r=>setTimeout(r,1));
  assert.equal(f.isRestoring(),true);
  const starting=f.send('start',{},'new-session');
  await new Promise(resolve=>setImmediate(resolve));assert.equal(f.contexts.length,1);
  f.restore();await stopping;assert.equal((await starting).ok,true);
  await f.send('stop',{},'new-session');assert.equal(pc.sender.track,pc.original);
});

test('hangup authorization only matches the current single audio peer and session',async()=>{
  const f=fixture(),old=new f.window.RTCPeerConnection();
  assert.equal((await f.send('hangup-check')).ok,false);
  await f.send('start');assert.equal((await f.send('hangup-check')).ok,true);
  assert.equal((await f.send('hangup-check',{},'stale-session')).ok,false);
  assert.equal(old.sender.track.id,'ai-audio','a failed check must not stop the current call');
  new f.window.RTCPeerConnection();assert.equal((await f.send('hangup-check')).ok,false);
  assert.equal(f.events.filter(x=>x.kind==='error').length,0);
  await f.send('stop');
});

test('a disconnected old peer cannot authorize ending a new peer on the same page',async()=>{
  const f=fixture(),old=new f.window.RTCPeerConnection();await f.send('start');old.close();
  new f.window.RTCPeerConnection();await new Promise(resolve=>setImmediate(resolve));
  assert.equal((await f.send('probe')).count,1);
  assert.equal((await f.send('hangup-check')).ok,false);
});
