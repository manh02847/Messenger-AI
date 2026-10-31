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
  const document={body:scope,querySelectorAll:()=>nodes,get cookie(){if(typeof cookie==='function')return cookie();return cookie;}};
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

function containerFixture(props={callInfo:{callerId:'222'}}) {
  const f=fixture();
  delete f.button.__reactProps$test;
  // Match the user's real DOM: only the root has a React fiber carrier;
  // call elements have event/listener/handle sets and no fiber/props expando.
  f.button.__reactEvents$test=new Set();
  f.button.__reactHandles$test=new Set();
  f.button.__reactListeners$test=new Set();
  const element={nodeType:1}, root={containerInfo:element};
  const current={tag:3,stateNode:root,memoizedProps:{callerID:'999'}};
  const old={tag:3,stateNode:root,memoizedProps:{callerID:'888'}};
  const unrelated={tag:0,memoizedProps:{callerID:'777',participants:['111','777','666']},return:current};
  const card={tag:5,stateNode:f.scope,memoizedProps:{},return:current};
  const component={tag:0,memoizedProps:props,return:card};
  const answer={tag:5,stateNode:f.button,memoizedProps:{},return:component};
  current.child=unrelated;unrelated.sibling=card;card.child=component;component.child=answer;
  root.current=current;old.alternate=current;current.alternate=old;
  element.__reactContainer$test=old;
  f.context.document.querySelectorAll=selector=>selector==='*'?[element,f.scope,...f.nodes]:f.nodes;
  return {...f,element,root,current,old,unrelated,card,component,answer};
}

test('root-only React DOM resolves just the branch rendering the marked incoming card',()=>{
  assert.equal(containerFixture().read().peer.callerId,'222');
});

test('container anchor uses root.current, not the initial, alternate or pending tree',()=>{
  const f=containerFixture();
  f.old.child={tag:5,stateNode:f.scope,memoizedProps:{callerID:'333'},
    child:{tag:5,stateNode:f.button,memoizedProps:{}}};
  f.component.pendingProps={callerID:'444'};
  assert.equal(f.read().peer.callerId,'222');
  f.root.current=f.old;
  assert.equal(f.read().peer.callerId,'333');
});

test('container branches use rendered children and their current parents rather than virtual child props',()=>{
  const f=containerFixture();
  f.component.return=f.unrelated;
  f.card.memoizedProps={children:{props:{callerID:'555'}}};
  let child=f.card.memoizedProps.children;
  for(let i=0;i<20;i++){child.props.children={props:{}};child=child.props.children;}
  assert.equal(f.read().peer.callerId,'222');
});

test('a caller is never recovered from an alternate whose DOM node is absent from the current tree',()=>{
  const f=containerFixture();
  f.old.child=f.card;f.current.child=f.unrelated;f.unrelated.sibling=null;
  assert.equal(f.read().code,'CALLER_ID_MISSING');
});

test('portal cards can be found even when the root DOM container is not a card ancestor',()=>{
  const f=containerFixture();
  const outside={nodeType:1};
  const host={tag:5,stateNode:outside,memoizedProps:{callerID:'555'},return:f.current};
  const portal={tag:4,stateNode:{containerInfo:{}},memoizedProps:{callerID:'666'},return:host};
  f.current.child=host;host.child=portal;portal.child=f.card;f.card.return=portal;
  assert.equal(f.scope.contains(f.element),false);
  assert.equal(f.read().peer.callerId,'222');
});

test('container metadata exposes only scoped field shapes and bounded traversal counts',()=>{
  const f=containerFixture({callInfo:{peerID:'222',name:'PRIVATE_NAME',token:'PRIVATE_TOKEN'}});
  const result=f.read();
  assert.equal(result.code,'CALLER_ID_MISSING');
  assert.equal(result.diagnostics.roots,1);
  assert.equal(result.diagnostics.walked,5);
  assert.equal(result.diagnostics.matched,2);
  assert.ok(result.diagnostics.fibers>0);
  assert.ok(result.diagnostics.reactTypes.includes('container'));
  assert.ok(result.diagnostics.fields.includes('props.callInfo.peerID=numeric-string'));
  for(const text of ['PRIVATE_NAME','PRIVATE_TOKEN','222','777','888','999'])assert.ok(!JSON.stringify(result).includes(text));
});

test('a root carrier must belong to its DOM container and current HostRoot',()=>{
  for(const invalidate of [f=>f.root.containerInfo={}, f=>f.current.tag=5,
    f=>f.current.stateNode={}, f=>f.root.current=null, f=>f.old.tag=0]) {
    const f=containerFixture();invalidate(f);
    assert.equal(f.read().code,'CALLER_ID_MISSING');
  }
});

test('container fallback never invokes expando, fiber or root getters',()=>{
  const f=containerFixture();
  Object.defineProperty(f.element,'__reactContainer$getter',{get(){throw Error('Do not run root getter');}});
  Object.defineProperty(f.unrelated,'memoizedProps',{get(){throw Error('Do not inspect unrelated props');}});
  Object.defineProperty(f.card,'pendingProps',{get(){throw Error('Do not inspect pending props');}});
  assert.equal(f.read().peer.callerId,'222');
});

test('a cyclic or oversized call-card subtree cannot return a partial caller guess',()=>{
  const cycle=containerFixture();cycle.answer.child=cycle.card;
  assert.equal(cycle.read().code,'CALL_CARD_TOO_LARGE');
  const large=containerFixture();
  let end=large.answer;
  for(let i=0;i<50000;i++){end.child={tag:0};end=end.child;}
  const result=large.read();
  assert.equal(result.code,'CALL_CARD_TOO_LARGE');
  assert.ok(result.diagnostics.walked<=50000);
  assert.ok(['branch','time'].includes(result.diagnostics.limit));
  assert.ok(result.diagnostics.matched>0);
  assert.equal(result.peer,undefined);
});

test('a deep unrelated feed larger than the old 10000-fiber cap cannot starve the call card',()=>{
  const f=containerFixture();
  let end=f.unrelated;
  for(let i=0;i<20000;i++){end.child={tag:0};end=end.child;}
  assert.equal(f.read().peer.callerId,'222');
  const diagnostic=containerFixture({callInfo:{peerID:'222'}});
  diagnostic.unrelated.child=f.unrelated.child;
  const result=diagnostic.read();
  assert.equal(result.code,'CALLER_ID_MISSING');
  assert.ok(result.diagnostics.walked<100);
  assert.equal(result.diagnostics.matched,2);
});

test('breadth-first search reaches the overlay before descending a feed with many branches',()=>{
  const f=containerFixture();
  const wrapper={tag:0,child:f.card};
  f.unrelated.sibling=wrapper;
  let sibling=null;
  for(let i=0;i<1000;i++) {
    let child={tag:0,sibling};sibling=child;
    for(let j=0;j<30;j++){child.child={tag:0};child=child.child;}
  }
  f.unrelated.child=sibling;
  assert.equal(f.read().peer.callerId,'222');
});

test('the whole selected card is inspected for conflicting profiles after the page search stops',()=>{
  const f=containerFixture();
  const avatar={nodeType:1,getAttribute:()=>null};f.nodes.push(avatar);
  f.card.child.sibling={tag:0,memoizedProps:{callerId:'333'},
    child:{tag:5,stateNode:avatar,memoizedProps:{}}};
  let end=f.unrelated;
  for(let i=0;i<20000;i++){end.child={tag:0};end=end.child;}
  assert.equal(f.read().code,'CALLER_AMBIGUOUS');
});

test('an exhausted search or wall-clock deadline keeps every caller private',()=>{
  const absent=containerFixture();absent.unrelated.sibling=null;
  let end=absent.unrelated;
  for(let i=0;i<50000;i++){end.child={tag:0};end=end.child;}
  const result=absent.read();
  assert.equal(result.code,'CALL_CARD_TOO_LARGE');
  assert.ok(['search','time'].includes(result.diagnostics.limit));
  assert.equal(result.peer,undefined);
  const slow=containerFixture();let elapsed=0;
  slow.context.performance={now:()=>{elapsed+=200;return elapsed;}};
  const timeout=slow.read();
  assert.equal(timeout.code,'CALL_CARD_TOO_LARGE');
  assert.equal(timeout.diagnostics.limit,'time');
  assert.equal(timeout.peer,undefined);
});

test('root-only active call state still needs the exact call_id before routing participants',()=>{
  for(const callID of ['one','two',undefined]) {
    const f=containerFixture({});
    f.component.memoizedState={memoizedState:{callID,participants:['111','222']}};
    f.context.location.href='https://www.facebook.com/groupcall/test?call_id=one';
    const result=f.api.readActive(f.context.location.href);
    assert.equal(result.code,callID==='one'?'RESOLVED':'CALLER_ID_MISSING');
    if(result.peer)assert.equal(result.peer.callerId,'222');
  }
});

function callURLFixture(query='thread_type=15&peer_id=222&av=111', options={}) {
  const f=fixture(options);
  f.context.location.href='https://www.messenger.com/groupcall/ROOM:555/?call_id=one&'+query;
  const key='https://www.messenger.com/groupcall/ROOM:555/?call_id=one';
  return {...f,key,active:()=>JSON.parse(JSON.stringify(f.api.readActive(key)))};
}

for(const type of ['1','7','13','15']) test(`private call URL type ${type} resolves before any React/DOM traversal`,()=>{
  const f=callURLFixture('thread_type='+type+'&peer_id=222&av=111&nonce=PRIVATE_NONCE&server_info_data=PRIVATE_SERVER');
  f.scope.querySelectorAll=()=>{throw Error('URL identity must not inspect React');};
  const result=f.active();
  assert.deepEqual(result,{code:'RESOLVED',peer:{ownerId:'111',callerId:'222'},method:'call-url'});
  assert.ok(!JSON.stringify(result).includes('PRIVATE'));
});

for(const query of [
  'thread_type=15&peer_id=222&peer_id=333&av=111',
  'thread_type=15&peer_id=222&av=111&av=111',
  'thread_type=15&thread_type=16&peer_id=222&av=111',
  'thread_type=15&peer_id=222', 'thread_type=15&av=111',
  'thread_type=15&peer_id=0&av=111', 'thread_type=15&peer_id=222%40msgr&av=111',
  'thread_type=15&peer_id=111&av=111', 'thread_type=15&peer_id=%20222&av=111',
  'thread_type=999&peer_id=222&av=111', 'peer_id=222&av=111',
  'thread_type=15&peer_id=222&av=0',
]) test(`ambiguous or invalid call URL cannot become a recipient: ${query}`,()=>{
  const f=callURLFixture(query,{props:{callID:'one',callerID:'444'}});
  assert.equal(f.active().code,'INVALID_PEER');
});

for(const type of ['2','8','11','16']) test(`group call URL type ${type} cannot route a private summary`,()=>{
  assert.equal(callURLFixture('thread_type='+type+'&peer_id=222&av=111').active().code,'GROUP_CALL');
});

test('the URL actor must match the account independently verified in the calling page',()=>{
  assert.equal(callURLFixture('thread_type=15&peer_id=222&av=333').active().code,'OWNER_MISMATCH');
  assert.equal(callURLFixture(undefined,{viewer:'0'}).active().code,'OWNER_ID_MISSING');
});

test('a call URL without identity fields keeps the React fallback and never interprets ROOM as a person',()=>{
  assert.equal(callURLFixture('',{props:{callID:'one',callerID:'222'}}).active().peer.callerId,'222');
  assert.equal(callURLFixture('').active().code,'CALLER_ID_MISSING');
});

test('call URL identity is bound to one trusted HTTPS call URL and a unique call_id',()=>{
  const f=callURLFixture();
  assert.equal(f.api.readActive(f.key.replace('one','two')).code,'RING_CHANGED');
  for(const href of [
    f.context.location.href+'&call_id=two',
    f.context.location.href.replace('https:','http:'),
    f.context.location.href.replace('www.messenger.com','example.test'),
    f.context.location.href.replace('www.messenger.com','user@www.messenger.com'),
    f.context.location.href.replace('www.messenger.com','www.messenger.com:8443'),
  ]) {
    const invalid=callURLFixture();invalid.context.location.href=href;
    const url=new URL(href), key=url.origin+url.pathname+'?call_id='+url.searchParams.get('call_id');
    assert.equal(invalid.api.readActive(key).code,'RING_CHANGED');
    assert.equal(invalid.calls(),0);
  }
});

test('a hook/context participant collection requires the verified owner and exactly one other profile',()=>{
  const active=f=>{f.context.location.href='https://www.facebook.com/groupcall/test?call_id=one';return f.api.readActive(f.context.location.href);};
  for(const value of [['111','222'],[{id:'111'},{id:'222'}],new Map([['111',{}],['222',{}]])]) {
    const f=fixture({fiber:true});
    f.button.__reactFiber$test.memoizedState={memoizedState:{callID:'one',participants:value},next:null};
    assert.equal(active(f).peer.callerId,'222');
  }
  const f=fixture({fiber:true});
  f.button.__reactFiber$test.dependencies={firstContext:{memoizedValue:{callID:'one',participantMap:new Map([['111',{}],['222',{}]])}}};
  assert.equal(active(f).peer.callerId,'222');
  const ref=fixture({fiber:true});
  ref.button.__reactFiber$test.memoizedState={memoizedState:{current:{callID:'one',participants:['111','222']}}};
  assert.equal(active(ref).peer.callerId,'222');
});

test('unbound, cached or another call state cannot route a current call summary',()=>{
  for(const state of [{participants:['111','333']},{callID:'two',participants:['111','333']},
    {callID:'one',history:{participants:['111','333']}},{isGroupCall:true,participants:['111','222','333']}]) {
    const f=fixture({fiber:true});f.context.location.href='https://www.facebook.com/groupcall/test?call_id=one';
    f.button.__reactFiber$test.memoizedState={memoizedState:state};
    assert.equal(f.api.readActive(f.context.location.href).code,'CALLER_ID_MISSING');
  }
});

test('unrelated participant lists and getters cannot infer a caller',()=>{
  for(const value of [['222','333'],['222'],['111','111']]) {
    assert.equal(fixture({props:{participants:value}}).read().code,'CALLER_ID_MISSING');
  }
  const people=['111','222'];Object.defineProperty(people,'0',{get(){throw Error('Do not invoke getters');}});
  assert.equal(fixture({props:{participants:people}}).read().code,'CALL_CARD_TOO_LARGE');
});

test('the active call reader checks the exact call URL and does not use a feed or another call',()=>{
  const f=fixture({props:{callID:'one',participants:['111','222']}});
  f.context.location.href='https://www.facebook.com/groupcall/ROOM:test?call_id=one';
  assert.equal(f.api.readActive(f.context.location.href).peer.callerId,'222');
  assert.equal(f.api.readActive('https://www.facebook.com/groupcall/ROOM:test?call_id=two').code,'RING_CHANGED');
  f.context.location.href='https://www.facebook.com/';
  assert.equal(f.api.readActive(f.context.location.href).code,'RING_CHANGED');
  const unrelated=fixture({props:{userID:'333'},attrs:{href:'/333'}});
  unrelated.context.location.href='https://www.facebook.com/groupcall/test?call_id=one';
  assert.equal(unrelated.api.readActive(unrelated.context.location.href).code,'CALLER_ID_MISSING');
});

test('structural diagnostics preserve field shapes without private values or dynamic key names',()=>{
  const f=fixture({props:{call:{otherUserFbId:'222',name:'PRIVATE_NAME',token:'PRIVATE_TOKEN',userAlice:'333',user123456789:'444'}}});
  const result=f.read();assert.equal(result.code,'CALLER_ID_MISSING');
  assert.ok(result.diagnostics.fields.includes('props.call.otherUserFbId=numeric-string'));
  const encoded=JSON.stringify(result);
  for(const text of ['PRIVATE_NAME','PRIVATE_TOKEN','Alice','123456789','222','333','444'])assert.ok(!encoded.includes(text));
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
  const location={origin:'https://www.facebook.com',href:'https://www.facebook.com/'};
  const context=vm.createContext({window,chrome,CallLabIncoming:incoming,crypto:{randomUUID},
    location,URL,setTimeout,clearTimeout});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../experimental/call-lab-extension/content.js'),'utf8'),context);
  return {requests,location,clicks:()=>clicks,change:()=>ring='ring-2',
    command:(name,details={})=>new Promise(resolve=>runtime({to:'call-lab-content',command:name,ringId:'ring-1',...details},{id},resolve)),
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

test('content forwards only the fixed URL source marker and bounded caller identity',async()=>{
  const f=contentFixture(),callKey='https://www.facebook.com/groupcall/test?call_id=one';
  f.location.href=callKey+'&peer_id=222&av=111&thread_type=15';
  const waiting=f.command('call-identity',{callKey});
  f.reply({code:'RESOLVED',method:'call-url',peer:{ownerId:'111',callerId:'222'},url:'PRIVATE_URL'});
  const result=await waiting;
  assert.equal(result.summaryIdentity.method,'call-url');
  assert.equal(result.summaryPeer.callerId,'222');
  assert.ok(!JSON.stringify(result).includes('PRIVATE_URL'));
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

test('root traversal counters survive the content boundary without unbounded or private fields',async()=>{
  const f=contentFixture(), waiting=f.command('auto-identity');
  f.reply({code:'CALLER_ID_MISSING',diagnostics:{source:'ring',reactTypes:['container','other'],
    roots:1,walked:18640,matched:43,limit:'time',nodes:10001,contexts:-1,maps:true,token:'DO_NOT_EXPORT',fields:[]}});
  const result=await waiting;
  assert.equal(result.summaryIdentity.version,'0.6.5');
  assert.deepEqual(JSON.parse(JSON.stringify(result.summaryIdentity.diagnostics)),{source:'ring',reactTypes:['container','other'],
    roots:1,walked:18640,matched:43,limit:'time',fields:[]});
  assert.ok(!JSON.stringify(result).includes('DO_NOT_EXPORT'));
});

test('unknown limit text and search counts above the cap never leave content',async()=>{
  const f=contentFixture(), waiting=f.command('auto-identity');
  f.reply({code:'CALL_CARD_TOO_LARGE',diagnostics:{source:'ring',walked:50001,limit:'DO_NOT_EXPORT'}});
  const result=await waiting;
  assert.equal(result.summaryIdentity.diagnostics.walked,undefined);
  assert.equal(result.summaryIdentity.diagnostics.limit,undefined);
  assert.ok(!JSON.stringify(result).includes('DO_NOT_EXPORT'));
});

for(const code of ['OWNER_MISMATCH','INVALID_PEER']) test(`URL identity rejection survives the content boundary: ${code}`,async()=>{
  const f=contentFixture(), waiting=f.command('auto-identity');
  f.reply({code,method:'PRIVATE_METHOD',url:'PRIVATE_URL'});
  const result=await waiting;
  assert.equal(result.summaryIdentity.code,code);
  assert.equal(result.summaryPeer,undefined);
  assert.ok(!JSON.stringify(result).includes('PRIVATE'));
});
