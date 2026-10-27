const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

function fixture({text='Incoming audio call. Someone is calling you', answer='Accept', decline='Decline', pathname='/'}={}) {
  let list=[], interval;
  const scope={textContent:text,querySelectorAll:()=>list};
  function button(name) {
    const item={innerText:name,isConnected:true,disabled:false,clicked:0,attrs:{},style:{display:'block',visibility:'visible'},
      getAttribute(key){return this.attrs[key] || null;},getBoundingClientRect(){return {width:50,height:20};},
      closest:()=>scope,click(){this.clicked++;}};
    list.push(item);return item;
  }
  const yes=button(answer), no=button(decline), events=[];
  const context=vm.createContext({document:{querySelectorAll:()=>list,body:{innerText:text}},location:{pathname},getComputedStyle:button=>button.style,
    crypto:{randomUUID},MutationObserver:class{observe(){}disconnect(){}},
    setTimeout:fn=>fn,clearTimeout(){},setInterval:fn=>{interval=fn;return fn;},clearInterval:()=>interval=null});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../experimental/call-lab-extension/incoming.js'),'utf8'),context);
  return {api:context.CallLabIncoming,yes,no,events,button,scope,scan:()=>interval?.(),
    enable(){this.api.watch(true,event=>events.push(event));},remove(item){list=list.filter(x=>x!==item);}};
}

test('incoming call detection is passive until armed and accepts a validated nonce once',()=>{
  const f=fixture();assert.equal(f.api.probe().ringId,null);assert.equal(f.yes.clicked,0);
  f.enable();assert.equal(f.events.length,1);const id=f.events[0].ringId;
  assert.equal(f.api.accept('wrong').ok,false);assert.equal(f.yes.clicked,0);
  assert.equal(f.api.accept(id).accepted,true);assert.equal(f.yes.clicked,1);
  assert.equal(f.api.accept(id).ok,false);
});

test('restoring the saved watch mode keeps the first ringing nonce valid and does not emit a duplicate',()=>{
  const f=fixture();f.enable();const first=f.events[0].ringId, restored=[];
  f.api.watch(true,event=>restored.push(event));f.scan();
  assert.equal(f.api.probe().ringId,first);
  assert.equal(f.events.length,1);assert.equal(restored.length,0);
  assert.equal(f.api.accept(first).accepted,true);
  assert.equal(f.api.accept(first).ok,false);
});

test('a restored watcher still reports the next call to its latest callback',()=>{
  const f=fixture();f.enable();const first=f.events[0].ringId, restored=[];
  f.api.watch(true,event=>restored.push(event));
  f.remove(f.yes);f.scan();f.button('Accept');f.scan();
  assert.equal(f.events.length,1);assert.equal(restored.length,1);
  assert.notEqual(restored[0].ringId,first);
  assert.equal(f.api.accept(first).ok,false);
  assert.equal(f.api.accept(restored[0].ringId).accepted,true);
});

test('Vietnamese call labels are recognized without passing caller names or text',()=>{
  const f=fixture({text:'Cuộc gọi thoại đến. Ai đó đang gọi cho bạn',answer:'Trả lời',decline:'Từ chối'});f.enable();
  assert.equal(f.events.length,1);assert.deepEqual(Object.keys(f.events[0]).sort(),['kind','ringId']);
});

for(const [name,patch] of [
  ['friend request',{text:'Friend request',answer:'Accept',decline:'Decline'}],
  ['outgoing call',{text:'Calling someone',answer:'Accept',decline:'Decline'}],
  ['generic reply',{text:'Reply to this message',answer:'Trả lời',decline:'Từ chối'}],
  ['video call',{text:'Incoming video call',answer:'Accept',decline:'Decline'}],
  ['labelled group call',{text:'Incoming audio call. Group call',answer:'Accept',decline:'Decline'}],
]) test(`does not answer ${name}`,()=>{const f=fixture(patch);f.enable();assert.equal(f.events.length,0);assert.equal(f.yes.clicked,0);});

for(const state of ['hidden','disabled','detached']) test(`does not click a ${state} answer button`,()=>{
  const f=fixture();if(state==='hidden')f.yes.style.display='none';if(state==='disabled')f.yes.disabled=true;if(state==='detached')f.yes.isConnected=false;
  f.enable();assert.equal(f.events.length,0);
});

test('changed or duplicated incoming buttons invalidate the previous nonce',()=>{
  const f=fixture();f.enable();const id=f.events[0].ringId;
  f.button('Accept');assert.equal(f.api.probe().ringId,null);assert.equal(f.api.accept(id).ok,false);
});

test('disarming prevents acceptance and hangup only uses a unique exact call control',()=>{
  const f=fixture();f.enable();const id=f.events[0].ringId;f.api.watch(false);
  assert.equal(f.api.accept(id).ok,false);
  assert.equal(f.api.hangup().ok,false);const end=f.button('End call');assert.equal(f.api.hangup().ok,true);assert.equal(end.clicked,1);
  f.button('End call');assert.equal(f.api.hangup().ok,false);
});

test('the rating screen in a call popup is reported even when auto answering is off',()=>{
  const f=fixture({pathname:'/groupcall/ROOM:TEST',text:'Bạn thấy chất lượng cuộc gọi như thế nào?',answer:'Đóng',decline:'Gọi lại'});
  assert.equal(f.api.endState().ended,true);f.api.watch(false,event=>f.events.push(event));
  assert.equal(f.events[0].kind,'call-ui');f.scan();assert.equal(f.events.length,2,'retry if the peer closes slightly later than the UI');
});

test('a rating phrase on the Facebook feed cannot trigger call cleanup',()=>{
  const f=fixture({pathname:'/',text:'Bạn thấy chất lượng cuộc gọi như thế nào?',answer:'Đóng',decline:'Gọi lại'});
  assert.equal(f.api.endState().ended,false);
});

test('a ringing or outgoing call on the home page blocks refreshing before audio connects',()=>{
  const f=fixture();assert.equal(f.api.endState().busy,true);
  const outgoing=fixture({answer:'End call',decline:'Mute microphone',text:'Calling someone'});
  assert.equal(outgoing.api.endState().busy,true);
  const idle=fixture({answer:'Like',decline:'Comment',text:'Facebook home'});
  assert.equal(idle.api.endState().busy,false);
});

test('friend request buttons do not block the home refresh',()=>{
  const f=fixture({text:'Friend request',answer:'Accept',decline:'Decline'});
  assert.equal(f.api.endState().busy,false);
});

for(const text of ['Incoming video call','Incoming audio call. Group call']) test(`${text} blocks refresh without being auto answered`,()=>{
  const f=fixture({text});f.enable();assert.equal(f.events.length,0);
  assert.equal(f.api.endState().busy,true);
});

for(const control of ['End call','Accept','Decline']) test(`a visible ${control} control suppresses cleanup of a stale rating panel`,()=>{
  const f=fixture({pathname:'/groupcall/test',text:'How was your call?',answer:'Close',decline:'Call again'});
  f.button(control);assert.equal(f.api.endState().ended,false);
});

test('handover requires an explicit another-device notice, not merely more speech',()=>{
  const f=fixture({pathname:'/groupcall/test',text:'This call was answered on another device',answer:'Close',decline:'Call again'});
  assert.equal(f.api.endState().handoff,true);
  const other=fixture({pathname:'/groupcall/test',text:'Someone is speaking',answer:'Close',decline:'Call again'});
  assert.equal(other.api.endState().handoff,false);
});
