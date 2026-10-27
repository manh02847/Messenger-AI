/* Offline WebRTC fixture only. No Facebook login, network or real call. */
const {createRequire} = require('node:module');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const requireTools = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? createRequire(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'package.json')) : require;
const {chromium} = requireTools('playwright');

const html = `<!doctype html><title>Local call fixture</title><p>Offline test</p><script>
window.fixture = {
 async start(frequency) {
  this.context = new AudioContext(); await this.context.resume();
  this.destination=this.context.createMediaStreamDestination();
  this.oscillator=this.context.createOscillator();this.oscillator.frequency.value=frequency;
  this.gain=this.context.createGain();this.gain.gain.value=.2;
  this.oscillator.connect(this.gain).connect(this.destination);this.oscillator.start();
  this.pc=new RTCPeerConnection({iceServers:[]});
  this.pc.addTrack(this.destination.stream.getAudioTracks()[0],this.destination.stream);
  this.pc.ontrack=event=>{
   this.analyser=this.context.createAnalyser();this.analyser.fftSize=4096;
   this.remote=this.context.createMediaStreamSource(new MediaStream([event.track]));
   this.silent=this.context.createGain();this.silent.gain.value=0;
   this.remote.connect(this.analyser).connect(this.silent).connect(this.context.destination);
  };
 },
 async local(offer) {
  if(offer) await this.pc.setRemoteDescription(offer);
  await this.pc.setLocalDescription(offer?await this.pc.createAnswer():await this.pc.createOffer());
  const until=Date.now()+5000;
  while(this.pc.iceGatheringState!=='complete'&&Date.now()<until) await new Promise(r=>setTimeout(r,20));
  return this.pc.localDescription.toJSON();
 },
 async remoteDescription(answer) {await this.pc.setRemoteDescription(answer);},
 peak() {
  if(!this.analyser)return 0;
  const bins=new Float32Array(this.analyser.frequencyBinCount);this.analyser.getFloatFrequencyData(bins);
  let best=4;for(let i=5;i<bins.length;i++)if(bins[i]>bins[best])best=i;
  return bins[best]>-70?best*this.context.sampleRate/this.analyser.fftSize:0;
 }
};
</script>`;

async function poll(check, note, timeout=10000) {
  const until=Date.now()+timeout;
  while(Date.now()<until){ if(await check())return;await new Promise(r=>setTimeout(r,80)); }
  throw new Error(note);
}
async function tone(page, frequency) {
  await poll(async()=>Math.abs(await page.evaluate(()=>fixture.peak())-frequency)<35,`Expected ${frequency} Hz at caller`);
}

(async()=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'call-lab-chrome-'));
  const extension=path.resolve(__dirname,'../experimental/call-lab-extension');
  let context;
  try {
    context=await chromium.launchPersistentContext(profile,{
      executablePath:process.env.CALL_LAB_CHROME,
      headless:true,
      args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`,'--no-sandbox','--autoplay-policy=no-user-gesture-required'],
    });
    context.setDefaultTimeout(10000);
    await context.route('https://www.facebook.com/__call_lab_fixture',route=>route.fulfill({body:html,contentType:'text/html'}));
    await context.route('https://www.facebook.com/__call_lab_home',route=>route.fulfill({body:'<!doctype html><title>Offline Facebook feed fixture</title><p>No call in this tab.</p>',contentType:'text/html'}));
    await context.route('https://caller.example.test/fixture',route=>route.fulfill({body:html,contentType:'text/html'}));
    let worker=context.serviceWorkers()[0];
    if(!worker)worker=await context.waitForEvent('serviceworker',{timeout:15000});
    const id=new URL(worker.url()).host;
    const home=await context.newPage();await home.goto('https://www.facebook.com/__call_lab_home');
    const [callee]=await Promise.all([
      context.waitForEvent('page'),
      home.evaluate(()=>window.open('/__call_lab_fixture','call-lab-fixture','popup,width=800,height=600')),
    ]);
    await callee.waitForLoadState('domcontentloaded');
    const caller=await context.newPage();await caller.goto('https://caller.example.test/fixture');
    await callee.evaluate(()=>fixture.start(220));
    await caller.evaluate(()=>fixture.start(440));
    const offer=await callee.evaluate(()=>fixture.local());
    const answer=await caller.evaluate(offer=>fixture.local(offer),offer);
    await callee.evaluate(answer=>fixture.remoteDescription(answer),answer);
    await poll(()=>callee.evaluate(()=>fixture.pc.connectionState==='connected'),'WebRTC did not connect');
    await tone(caller,220);
    const popup=await context.newPage();await popup.goto(`chrome-extension://${id}/popup.html`);
    await popup.locator('#endpoint').fill(process.env.CALL_LAB_TEST_URL);
    await popup.locator('#token').fill(process.env.CALL_LAB_TEST_TOKEN);
    await popup.locator('#monitor').uncheck();
    await home.bringToFront();
    await popup.evaluate(()=>document.querySelector('#start').click());
    await poll(async()=> (await popup.locator('#status').textContent()).includes('AI đang nghe'), 'Extension did not start');
    await tone(caller,660);
    await tone(caller,880);
    await home.bringToFront();await popup.evaluate(()=>document.querySelector('#stop').click());
    await tone(caller,220);
    await poll(async()=> (await popup.locator('#status').textContent()).includes('Đã dừng'), 'Stop was not reflected in the popup');
    await home.bringToFront();await popup.evaluate(()=>document.querySelector('#start').click());
    await poll(async()=> (await popup.locator('#status').textContent()).includes('AI đang nghe'), 'Second session did not start');
    await tone(caller,660);
    await tone(caller,220);
    await poll(async()=> !(await popup.locator('#status').textContent()).includes('AI đang nghe'), 'Network failure did not stop the extension');
    console.log(JSON.stringify({webrtc:'passed',ai_audio:'passed',interruption:'passed',restore_microphone:'passed',disconnect_restore:'passed',browser:context.browser().version()}));
  } finally {
    if(context)await context.close();
    fs.rmSync(profile,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error.stack);process.exit(1);});
