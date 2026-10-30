/* Synthetic call-card/React data only; no Facebook account or browser session. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

function fixture({cookie='', viewer='111', props={}, attrs={}, extra=[], fiber=false, text='Incoming audio call. Caller is calling you'}={}) {
  const scope={textContent:text,nodeType:1,attrs:{},getAttribute(key){return this.attrs[key] || null;}};
  const button={isConnected:true,nodeType:1,attrs:{'data-messenger-ai-ring':'ring-1',...attrs},
    getAttribute(key){return this.attrs[key] || null;},closest:()=>scope};
  const nodes=[button,...extra];
  scope.querySelectorAll=()=>nodes;
  scope.contains=node=>node===scope||nodes.includes(node);
  let calls=0;
  if (fiber) button.__reactFiber$test={memoizedProps:{},return:{memoizedProps:props,return:{stateNode:scope}}};
  else button.__reactProps$test=props;
  const document={querySelectorAll:()=>nodes,get cookie(){if(typeof cookie==='function')return cookie();return cookie;}};
  const context=vm.createContext({document,location:{href:'https://www.facebook.com/'},URL,
    require:name=>{calls++;assert.equal(name,'CurrentUserInitialData');return{USER_ID:viewer,token:'DO_NOT_EXPORT'};}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../experimental/call-lab-extension/caller-main.js'),'utf8'),context);
  return {scope,button,nodes,api:context.CallLabCaller,context,read:()=>JSON.parse(JSON.stringify(context.CallLabCaller.read('ring-1'))),calls:()=>calls};
}

test('reader is passive until queried and resolves a caller without a numeric profile link',()=>{
  const f=fixture({props:{call:{callerID:'222',callID:'PRIVATE_CALL',text:'PRIVATE_WORDS'}}});
  assert.equal(f.calls(),0);
  assert.deepEqual(f.read(),{code:'RESOLVED',peer:{ownerId:'111',callerId:'222'}});
});

test('MAIN account data works when c_user is hidden or cookie access throws',()=>{
  const f=fixture({cookie:()=>{throw Error('HttpOnly/unavailable');},props:{incomingCall:{caller:{id:'222'}}}});
  assert.equal(f.read().peer.callerId,'222');
});

test('React fiber props of the incoming card resolve its caller',()=>{
  assert.equal(fixture({fiber:true,props:{callInfo:{callerId:'222'}}}).read().peer.callerId,'222');
});

for(const [key,value] of [['actorID','222'],['userId','222'],['actor',{id:'222',name:'PRIVATE_NAME'}],['profile',{id:'222'}]]) {
  test(`only numeric profile metadata from the call card is returned: ${key}`,()=>{
    const f=fixture({props:{[key]:value,children:{props:{user:{id:'111'}}},cookie:'NOT_EXPORTED'}});
    const result=f.read();assert.equal(result.peer.callerId,'222');
    assert.ok(!JSON.stringify(result).includes('PRIVATE'));
  });
}

for(const attrs of [{'data-userid':'222'},{'data-profile-id':'222'},{'data-hovercard':'/ajax/hovercard/user.php?id=222'},
  {href:'/profile.php?id=222'},{href:'/people/Caller/222/'}]) {
  test(`profile identity attributes are scoped to the marked call card: ${JSON.stringify(attrs)}`,()=>{
    assert.equal(fixture({attrs}).read().peer.callerId,'222');
  });
}

test('cookie owner fallback is numeric only and conflicts do not select an account',()=>{
  assert.equal(fixture({viewer:'0',cookie:'c_user=111; xs=DO_NOT_EXPORT',props:{callerID:'222'}}).read().peer.ownerId,'111');
  assert.equal(fixture({viewer:'111',cookie:'c_user=333',props:{callerID:'222'}}).read().code,'OWNER_ID_MISSING');
  assert.equal(fixture({viewer:'0',props:{callerID:'222'}}).read().code,'OWNER_ID_MISSING');
});

for(const props of [{id:'222',threadID:'222',roomID:'222'},{callerID:9007199254740992},
  {callerID:'222@msgr'},{callerID:'222@g.us'},{callerID:'0'}]) {
  test(`thread/room/generic IDs and invalid numbers cannot become a caller: ${JSON.stringify(props)}`,()=>{
    assert.equal(fixture({props}).read().code,'CALLER_ID_MISSING');
  });
}

test('a reused card with several profiles or explicit group data is not routed',()=>{
  assert.equal(fixture({props:{callerID:'222',actorID:'333'}}).read().code,'CALLER_AMBIGUOUS');
  assert.equal(fixture({props:{call:{callerID:'222',isGroupCall:true}}}).read().code,'GROUP_CALL');
  assert.equal(fixture({props:{call:{callerID:'222',participants:['111','222','333']}}}).read().code,'GROUP_CALL');
});

test('the same profile repeated in props is deduplicated; getters and cycles are not followed',()=>{
  const props={callerID:'222',nested:{inviterId:'222'}};props.loop=props;
  Object.defineProperty(props,'token',{get(){throw Error('Must not invoke getters');}});
  assert.equal(fixture({props}).read().peer.callerId,'222');
});

test('metadata traversal stops at its budget and does not return a partial guess',()=>{
  const props={callerID:'222',data:{}};let current=props.data;
  for(let i=0;i<15;i++){current.next={};current=current.next;}
  assert.equal(fixture({props}).read().code,'CALL_CARD_TOO_LARGE');
});

test('unrelated page profiles and non-call text cannot be used as a recipient',()=>{
  const f=fixture();f.context.user={id:'222'};
  assert.equal(f.read().code,'CALLER_ID_MISSING');
  assert.equal(fixture({text:'Friend request',props:{callerID:'222'}}).read().code,'RING_CHANGED');
});

test('unknown/expired/duplicated ring markers cannot select a caller',()=>{
  const f=fixture({props:{callerID:'222'}});
  assert.equal(f.api.read('wrong').code,'RING_CHANGED');
  f.button.isConnected=false;assert.equal(f.read().code,'RING_CHANGED');
  f.button.isConnected=true;f.nodes.push(f.button);assert.equal(f.read().code,'RING_CHANGED');
});

test('profiles outside the card are not traversed through the React tree',()=>{
  const f=fixture({fiber:true,props:{callerID:'222'}});
  const cardFiber=f.button.__reactFiber$test.return.return;
  cardFiber.return={memoizedProps:{actorID:'333',children:{props:{user:{id:'444'}}}}};
  assert.equal(f.read().peer.callerId,'222');
});

function contentFixture() {
  let runtime, ring='ring-1', clicks=0;
  const listeners=[], requests=[], id='b'.repeat(32);
  const window={postMessage:msg=>requests.push(msg),addEventListener:(_,fn)=>listeners.push(fn)};
  const incoming={watch(){},probe:()=>({ringId:ring}),mark:value=>value===ring,
    accept(value){if(value!==ring)return{ok:false};clicks++;ring=null;return{ok:true,accepted:true};}};
  const chrome={runtime:{id,onMessage:{addListener:fn=>runtime=fn},sendMessage:async()=>({watch:false})}};
  const context=vm.createContext({window,chrome,CallLabIncoming:incoming,crypto:{randomUUID},
    location:{origin:'https://www.facebook.com'},setTimeout,clearTimeout});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../experimental/call-lab-extension/content.js'),'utf8'),context);
  return {requests,clicks:()=>clicks,change:()=>ring='ring-2',
    command:name=>new Promise(resolve=>runtime({to:'call-lab-content',command:name,ringId:'ring-1'},{id},resolve)),
    reply(identity){const request=requests.at(-1);for(const listener of listeners)listener({source:window,
      data:{channel:request.channel,direction:'event',kind:'reply',requestId:request.requestId,ok:true,identity}});}};
}

test('content requests MAIN metadata without accepting and only returns bounded identity fields',async()=>{
  const f=contentFixture(), waiting=f.command('auto-identity');
  assert.equal(f.requests.at(-1).command,'incoming-peer');assert.equal(f.clicks(),0);
  f.reply({code:'RESOLVED',peer:{ownerId:'111',callerId:'222'},private:'DO_NOT_EXPORT'});
  const result=await waiting;assert.equal(result.summaryPeer.callerId,'222');
  assert.ok(!JSON.stringify(result).includes('DO_NOT_EXPORT'));assert.equal(f.clicks(),0);
  assert.equal((await f.command('auto-accept')).accepted,true);assert.equal(f.clicks(),1);
});

test('content discards metadata if the incoming ring changes while MAIN is reading',async()=>{
  const f=contentFixture(), waiting=f.command('auto-identity');f.change();
  f.reply({code:'RESOLVED',peer:{ownerId:'111',callerId:'222'}});
  assert.equal((await waiting).ok,false);assert.equal(f.clicks(),0);
  assert.equal((await f.command('auto-accept')).ok,false);
});

test('invalid peer objects or unrecognized diagnostic text never leave content',async()=>{
  const f=contentFixture(), waiting=f.command('auto-identity');
  f.reply({code:'RESOLVED',peer:{ownerId:'111',callerId:'222',token:'DO_NOT_EXPORT'}});
  const result=await waiting;assert.equal(result.summaryPeer,undefined);assert.equal(result.summaryIdentity.code,'INVALID_PEER');
  assert.ok(!JSON.stringify(result).includes('DO_NOT_EXPORT'));
});
