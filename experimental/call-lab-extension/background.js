let current = null;
let starting = false;
let attempt = 0;
const DEFAULT_ANSWER_DELAY = 25;
let automation = {enabled: false, answerDelaySeconds: DEFAULT_ANSWER_DELAY};
let explicitlyStopped = false;
let autoRevision = 0;
const triedRings = new Set();
const cleaning = new Map();
const callTabs = new Map();
let refreshRevision = 0;
let status = "Chưa bật AI. Nhận cuộc gọi rồi bật AI; tiện ích tự tìm cửa sổ đang gọi.";
const FACEBOOK_URLS = ["https://www.facebook.com/*", "https://web.facebook.com/*", "https://www.messenger.com/*", "https://messenger.com/*"];
const ERRORS = {
  NO_CALL: "Chưa thấy cuộc gọi đã kết nối. Tải lại Facebook sau khi cài/cập nhật tiện ích rồi gọi lại và nhận thủ công.",
  MULTIPLE_CALLS: "Có nhiều cuộc gọi hoặc luồng âm thanh. Chỉ giữ một cuộc gọi trong các tab/cửa sổ Facebook rồi thử lại.",
  AUDIO_PERMISSION: "Bấm vào trang cuộc gọi để cho phép âm thanh rồi bật lại AI.",
  AUDIO_BACKLOG: "Âm thanh bị dồn; đã dừng AI và trả micro.",
  BRIDGE_NOT_READY: "Chưa gắn được tiện ích vào cửa sổ gọi. Tải lại Facebook rồi mở cuộc gọi mới sau khi cập nhật tiện ích.",
};
function label(result) { return ERRORS[result?.code] || "Chưa nối được âm thanh; đã trả lại micro."; }
function supported(url) {
  try { const parsed = new URL(url); return parsed.protocol === "https:" && ["www.facebook.com", "web.facebook.com", "www.messenger.com", "messenger.com"].includes(parsed.hostname); }
  catch { return false; }
}
function endpointURL(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== "ws:" || !["127.0.0.1", "localhost"].includes(parsed.hostname)
      || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/") throw new Error("ENDPOINT");
  return parsed.href;
}
function callIdentity(value) {
  if (!supported(value)) return "";
  const url = new URL(value);
  if (!/^\/(?:groupcall|call|calls)(?:\/|$)/.test(url.pathname)) return "";
  return url.origin + url.pathname + "?call_id=" + (url.searchParams.get("call_id") || "");
}
async function takeover() {
  await stop("Đã nhường cuộc gọi cho người thật; AI dừng, tự nhận cuộc gọi sau vẫn giữ theo lựa chọn.", {hangup: false});
}
async function endCall(state, requestId, expiresAt) {
  if (typeof requestId !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(requestId)
      || state.endRequests.has(requestId)) return;
  state.endRequests.add(requestId);
  if (state.ending) return;
  let ok = false;
  try {
    if (current === state && state.ready && Number.isFinite(expiresAt) && Date.now() < expiresAt) {
      state.ending = true;
      const tab = await chrome.tabs.get(state.tabId);
      if (current === state && Date.now() < expiresAt && supported(tab?.url) && !tab.pendingUrl && tab.status !== "loading"
          && (!state.callKey || callIdentity(tab.url) === state.callKey)) {
        const result = await content(state, "end-call", {callKey: state.callKey, expiresAt});
        ok = result?.ok === true;
      }
    }
  } catch { /* A missing button or changed call leaves the current call alone. */ }
  if (current !== state) return;
  state.ending = false;
  try {
    if (state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({type: "end_call_result", requestId, ok}));
  } catch {}
  if (ok) await stop("Đã kết thúc cuộc gọi theo yêu cầu; tự nhận cuộc gọi sau vẫn giữ theo lựa chọn.", {hangup: false});
  else status = "Chưa kết thúc được cuộc gọi theo yêu cầu; kiểm tra nút kết thúc trên trang gọi.";
}
async function refreshHome(preferredTabId) {
  const revision = ++refreshRevision;
  const idle = () => revision === refreshRevision && !current && !starting;
  const quiet = (tab, ui) => ui?.ok === true && ui.count === 0 && ui.busy === false
    && !ui.handoff && (!callIdentity(tab.url) || ui.ended === true);
  try {
    await new Promise(resolve => setTimeout(resolve, 1500));
    if (!idle()) return;
    const tabs = (await chrome.tabs.query({url: FACEBOOK_URLS})).filter(tab => supported(tab.url));
    const homes = tabs.filter(tab => !callIdentity(tab.url));
    const home = homes.find(tab => tab.id === preferredTabId) || homes.find(tab => tab.active) || homes[0];
    if (!home || tabs.some(tab => tab.pendingUrl || tab.status === "loading")) return;
    // Both peer state and visible controls matter: a ringing/outgoing call can
    // have no connected audio peer yet. Unknown pages cancel this refresh.
    const checks = await Promise.all(tabs.map(async tab => quiet(tab,
      await chrome.tabs.sendMessage(tab.id, {to: "call-lab-content", command: "ui-probe"}, {frameId: 0}))));
    if (!idle() || checks.some(ok => !ok)) return;
    const latest = (await chrome.tabs.query({url: FACEBOOK_URLS})).filter(tab => supported(tab.url));
    if (!idle() || latest.length !== tabs.length || latest.some(tab => tab.pendingUrl || tab.status === "loading"
        || !tabs.some(old => old.id === tab.id && old.url === tab.url))) return;
    const ui = await chrome.tabs.sendMessage(home.id, {to: "call-lab-content", command: "ui-probe"}, {frameId: 0});
    const final = await chrome.tabs.get(home.id);
    if (!idle() || !quiet(home, ui) || final.pendingUrl || final.status === "loading" || final.url !== home.url) return;
    await chrome.tabs.reload(home.id);
    if (idle()) status = "Đã kết thúc cuộc gọi và tải lại trang Facebook; tự nhận giữ theo lựa chọn.";
  } catch { /* Keep the home page when a probe fails, navigates or disappears. */ }
}
async function onCallUI(tab) {
  const identity = callIdentity(tab.url);
  if (!identity || cleaning.has(tab.id)) return;
  const marker = {};
  cleaning.set(tab.id, marker);
  try {
    if (callTabs.get(tab.id)?.callKey && callTabs.get(tab.id).callKey !== identity) return;
    if (current?.tabId === tab.id && current.callKey && current.callKey !== identity) return;
    let ui = await chrome.tabs.sendMessage(tab.id, {to: "call-lab-content", command: "ui-probe"}, {frameId: 0});
    if (callTabs.get(tab.id)?.callKey && callTabs.get(tab.id).callKey !== identity) return;
    if (current?.tabId === tab.id && current.callKey && current.callKey !== identity) return;
    if (ui?.ok && ui.handoff) {
      const tracked = callTabs.get(tab.id);
      if (tracked) tracked.handedOff = true;
      if (current?.tabId === tab.id) await takeover();
    }
    if (!ui?.ok || ui.ended !== true || ui.count !== 0) return;
    const homeTabId = callTabs.get(tab.id)?.homeTabId ?? current?.automatic?.tabId;
    const handedOff = ui.handoff === true;
    if (current?.tabId === tab.id) await stop("Cuộc gọi đã kết thúc; AI dừng.", {hangup: false});
    await new Promise(resolve => setTimeout(resolve, 1000));
    if (cleaning.get(tab.id) !== marker) return;
    const tabs = await chrome.tabs.query({url: FACEBOOK_URLS});
    // Keep a Facebook/Messenger home tab so the VPS browser stays available.
    if (!tabs.some(other => other.id !== tab.id && supported(other.url) && !callIdentity(other.url))) return;
    const latest = await chrome.tabs.get(tab.id);
    if (latest.pendingUrl || callIdentity(latest.url) !== identity) return;
    ui = await chrome.tabs.sendMessage(tab.id, {to: "call-lab-content", command: "ui-probe"}, {frameId: 0});
    if (cleaning.get(tab.id) !== marker || !ui?.ok || ui.ended !== true || ui.count !== 0) return;
    const closing = await chrome.tabs.get(tab.id);
    if (cleaning.get(tab.id) !== marker || closing.pendingUrl || callIdentity(closing.url) !== identity) return;
    await chrome.tabs.remove(tab.id);
    callTabs.delete(tab.id);
    if (!current) status = "Đã dọn cửa sổ cuộc gọi đã kết thúc; giữ trang Facebook chính.";
    if (!handedOff && !ui.handoff) await refreshHome(homeTabId);
  } catch { /* A missing, navigated or closed tab is never removed speculatively. */ }
  finally { if (cleaning.get(tab.id) === marker) cleaning.delete(tab.id); }
}
function options(msg) {
  const endpoint = endpointURL(msg.endpoint);
  if (typeof msg.token !== "string" || msg.token.length < 20 || msg.token.length > 200) throw new Error("TOKEN");
  return {endpoint, token: msg.token, monitor: msg.monitor === true};
}
function answerDelay(value = DEFAULT_ANSWER_DELAY) {
  if (!Number.isInteger(value) || value < 0 || value > 90) throw new Error("ANSWER_DELAY");
  return value;
}
async function watchTabs(enabled) {
  const tabs = await chrome.tabs.query({url: FACEBOOK_URLS});
  await Promise.allSettled(tabs.filter(tab => supported(tab.url)).map(tab =>
    chrome.tabs.sendMessage(tab.id, {to: "call-lab-content", command: "auto-watch", enabled}, {frameId: 0})));
}
async function restoreAutomation() {
  try {
    await chrome.storage.local.setAccessLevel?.({accessLevel: "TRUSTED_CONTEXTS"});
    const saved = (await chrome.storage.local.get("callAutomation")).callAutomation;
    if (saved?.enabled === true && !explicitlyStopped) {
      automation = {...options(saved), answerDelaySeconds: answerDelay(saved.answerDelaySeconds), enabled: true};
      await watchTabs(true);
      status = "Đã khôi phục chế độ tự nhận cuộc gọi thoại và bật AI.";
    }
  } catch { automation = {enabled: false, answerDelaySeconds: DEFAULT_ANSWER_DELAY}; }
}
async function saveAutomation(msg) {
  const revision = ++autoRevision;
  await automationReady;
  if (revision !== autoRevision) return;
  const next = msg.autoEnabled === true
    ? {...options(msg), answerDelaySeconds: answerDelay(msg.answerDelaySeconds), enabled: true}
    : {...automation, enabled: false};
  if (!next.enabled) {
    explicitlyStopped = true;
    automation = next;
    if (current?.automatic) await stop();
  }
  await chrome.storage.local.set({callAutomation: next});
  if (revision !== autoRevision) {
    if (explicitlyStopped) await chrome.storage.local.set({callAutomation: {...automation, enabled: false}});
    return;
  }
  automation = next;
  explicitlyStopped = !next.enabled;
  await watchTabs(next.enabled);
  if (!next.enabled && current?.automatic) await stop();
  if (!current) status = next.enabled ? `Đã bật tự nhận sau ít nhất ${next.answerDelaySeconds} giây nếu chưa có người nghe. Giữ Chrome chạy trên VPS.` : "Đã tắt tự nhận cuộc gọi.";
}
async function stopAutomation() {
  const revision = ++autoRevision;
  explicitlyStopped = true;
  const enabled = automation.enabled;
  automation = {...automation, enabled: false};
  // Restore the microphone immediately even if persistent storage is broken.
  const ending = stop();
  await automationReady;
  if (revision === autoRevision) {
    try { await chrome.storage.local.set({callAutomation: automation}); }
    catch { status = "Đã dừng AI nhưng chưa lưu được tắt tự động; kiểm tra lại trước khi mở lại Chrome."; }
  }
  if (enabled) {
    try { await watchTabs(false); } catch {}
  }
  await ending;
}
async function incomingCalls() {
  const tabs = await chrome.tabs.query({url: FACEBOOK_URLS});
  const checks = await Promise.all(tabs.filter(tab => supported(tab.url)).map(async tab => {
    try {
      const result = await chrome.tabs.sendMessage(tab.id, {to: "call-lab-content", command: "auto-probe"}, {frameId: 0});
      return result?.ok && typeof result.ringId === "string" ? {tabId: tab.id, ringId: result.ringId} : null;
    } catch { return null; }
  }));
  return checks.filter(Boolean);
}
function wakeAnswer(state) {
  clearTimeout(state.answerTimer);
  state.answerTimer = null;
  const resolve = state.answerWake;
  state.answerWake = null;
  resolve?.();
}
async function waitForAutomatic(state, requested, revision) {
  while (current === state && automation.enabled && attempt === revision) {
    const found = await findCall(revision, state.id);
    if (current !== state || attempt !== revision) return false;
    if (found.tab || found.code === "MULTIPLE_CALLS") {
      await stop("Đã có người nhận hoặc đang có cuộc gọi khác; AI không tự tham gia.", {hangup: false});
      return false;
    }
    const rings = await incomingCalls();
    if (current !== state || attempt !== revision) return false;
    if (!automation.enabled || rings.length !== 1
        || rings[0].tabId !== requested.tabId || rings[0].ringId !== requested.ringId) {
      await stop("Cuộc gọi không còn chờ nhận; AI không tham gia.", {hangup: false});
      return false;
    }
    const remaining = Math.max(0, requested.answerAt - performance.now());
    if (state.googleReady && remaining === 0) return true;
    status = remaining > 0
      ? `Ưu tiên bạn nghe trước; AI chờ thêm ${Math.ceil(remaining / 1000)} giây nếu cuộc gọi vẫn đổ chuông.`
      : "Đã hết thời gian chờ; đang chờ Google sẵn sàng, chưa nhận cuộc gọi.";
    await new Promise(resolve => {
      state.answerWake = resolve;
      state.answerTimer = setTimeout(() => wakeAnswer(state), Math.min(1000, remaining || 1000));
    });
  }
  return false;
}
async function prepareAutomatic(state, requested, revision) {
  const found = await findCall(revision, state.id);
  if (current !== state || attempt !== revision || found.tab || found.code === "MULTIPLE_CALLS") throw new Error("RING_CHANGED");
  const rings = await incomingCalls();
  if (current !== state || !automation.enabled || rings.length !== 1
      || rings[0].tabId !== requested.tabId || rings[0].ringId !== requested.ringId
      || performance.now() < requested.answerAt) throw new Error("RING_CHANGED");
  let identity;
  try {
    identity = await chrome.tabs.sendMessage(requested.tabId,
      {to: "call-lab-content", command: "auto-identity", ringId: requested.ringId}, {frameId: 0});
  } catch {}
  if (current !== state || !automation.enabled || attempt !== revision) throw new Error("CANCELLED");
  if (identity?.summaryIdentity?.code === "GROUP_CALL") throw new Error("RING_CHANGED");
  // Identity lookup is read-only. Recheck takeover and the ring before clicking.
  const latest = await findCall(revision, state.id), freshRings = await incomingCalls();
  if (current !== state || !automation.enabled || attempt !== revision || latest.tab || latest.code === "MULTIPLE_CALLS"
      || freshRings.length !== 1 || freshRings[0].tabId !== requested.tabId || freshRings[0].ringId !== requested.ringId) throw new Error("RING_CHANGED");
  const accepted = await chrome.tabs.sendMessage(requested.tabId,
    {to: "call-lab-content", command: "auto-accept", ringId: requested.ringId}, {frameId: 0});
  if (!accepted?.accepted) throw new Error("RING_CHANGED");
  state.accepted = true;
  const captured = identity?.ok && identity.ringId === requested.ringId ? identity : null;
  state.summaryPeer = captured?.summaryPeer || (captured?.summaryIdentity?.code === "MAIN_BRIDGE_MISSING" || !captured ? accepted.summaryPeer : null) || null;
  state.summaryIdentity = captured?.summaryIdentity || {code: "EXTENSION_METADATA_MISSING"};
  if (state.summaryPeer && accepted.summaryPeer && (state.summaryPeer.ownerId !== accepted.summaryPeer.ownerId
      || state.summaryPeer.callerId !== accepted.summaryPeer.callerId)) {
    state.summaryPeer = null;
    state.summaryIdentity = {code: "CALLER_AMBIGUOUS"};
  }
  for (let i = 0; i < 25; i++) {
    if (current !== state || !automation.enabled) throw new Error("CANCELLED");
    const found = await findCall(revision, state.id);
    if (found.tab) {
      state.tabId = found.tab.id; state.callKey = callIdentity(found.tab.url);
      if (!state.summaryPeer && state.summaryIdentity?.code === "CALLER_ID_MISSING" && state.callKey) {
        let connected;
        try {connected = await content(state,"call-identity",{callKey:state.callKey});} catch {}
        if (current !== state || !automation.enabled || attempt !== revision) throw new Error("CANCELLED");
        const latest = await chrome.tabs.get(state.tabId);
        if (current !== state || attempt !== revision || callIdentity(latest.url) !== state.callKey) throw new Error("RING_CHANGED");
        if (connected?.ok && connected.callKey === state.callKey) {
          state.summaryPeer = connected.summaryPeer || null;
          state.summaryIdentity = connected.summaryIdentity || state.summaryIdentity;
        }
      }
      return;
    }
    if (found.code === "MULTIPLE_CALLS") throw new Error("MULTIPLE_CALLS");
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error("NO_CALL");
}
async function onIncoming(tabId, ringId) {
  const observedAt = performance.now();
  refreshRevision++;
  await automationReady;
  const key = String(tabId) + ":" + ringId;
  if (!automation.enabled || typeof ringId !== "string" || !ringId || ringId.length > 100 || triedRings.has(key)) return;
  const pending = current;
  if (pending?.automatic && !pending.accepted) {
    const rings = await incomingCalls();
    if (rings.length !== 1 || rings[0].tabId !== tabId || rings[0].ringId !== ringId) return;
    if (current === pending) await stop("Lượt gọi cũ không còn; đang kiểm tra lượt gọi mới.", {hangup: false});
    else if (current || starting) return;
  }
  if (!automation.enabled || current || starting) return;
  triedRings.add(key);
  if (triedRings.size > 100) triedRings.delete(triedRings.values().next().value);
  try { await start(automation, {tabId, ringId, answerAt: observedAt + automation.answerDelaySeconds * 1000}); }
  catch { status = "Chưa tự nối được cuộc gọi; kiểm tra relay và thử thủ công."; }
}
async function content(state, command, details = {}) {
  return chrome.tabs.sendMessage(state.tabId, {to: "call-lab-content", session: state.id, command, ...details}, {frameId: 0});
}
async function findCall(revision, session) {
  // Calls may live in a popup window while the action is opened on the feed.
  // Probe matching Facebook tabs only; do not read titles, chats or caller names.
  const tabs = await chrome.tabs.query({url: FACEBOOK_URLS});
  if (attempt !== revision) return {cancelled: true};
  const eligible = tabs.filter(tab => Number.isInteger(tab.id) && tab.id >= 0 && supported(tab.url));
  const results = await Promise.all(eligible.map(async tab => {
    try {
      const check = await chrome.tabs.sendMessage(tab.id, {to: "call-lab-content", command: "probe", session}, {frameId: 0});
      return {tab, check};
    } catch { return {tab, check: {ok: false}}; }
  }));
  if (attempt !== revision) return {cancelled: true};
  const available = results.filter(({check}) => check?.ok === true && Number.isInteger(check.count) && check.count >= 0);
  const calls = available.filter(({check}) => check.count > 0);
  if (calls.length > 1 || calls.some(({check}) => check.count > 1)) return {code: "MULTIPLE_CALLS"};
  if (calls.length === 1) return {tab: calls[0].tab};
  return {code: results.length > available.length ? "BRIDGE_NOT_READY" : "NO_CALL"};
}
async function stop(text = "Đã dừng AI và trả lại micro cho cuộc gọi.", {hangup = true} = {}) {
  attempt++;
  starting = false;
  const state = current;
  current = null;
  status = text;
  if (!state) return;
  wakeAnswer(state);
  clearInterval(state.keepalive);
  try { if (state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({type: "stop"})); } catch {}
  try { state.ws.close(); } catch {}
  if (hangup && state.automatic && state.accepted) {
    try { await content(state, "auto-hangup"); } catch {}
  }
  try { await content(state, "stop"); } catch {}
}
async function start(msg, automatic = null) {
  if (current || starting) throw new Error("ACTIVE");
  refreshRevision++;
  const {endpoint} = options(msg);
  const revision = ++attempt;
  starting = true;
  try {
    status = "Đang tìm cuộc gọi trong các cửa sổ Facebook/Messenger…";
    const id = crypto.randomUUID();
    const found = await findCall(revision, id);
    if (found.cancelled || attempt !== revision) return;
    if (automatic && (found.tab || found.code === "MULTIPLE_CALLS")) { status = "Đang có cuộc gọi khác; không tự nhận thêm."; return; }
    if (!automatic && !found.tab) { status = label(found); return; }
    if (automatic) {
      const rings = await incomingCalls();
      if (attempt !== revision || !automation.enabled || rings.length !== 1
          || rings[0].tabId !== automatic.tabId || rings[0].ringId !== automatic.ringId) return;
    }
    const tab = automatic ? {id: automatic.tabId} : found.tab;
    await chrome.storage.session.set({endpoint, token: msg.token, monitor: msg.monitor === true});
    if (attempt !== revision) return;
    const ws = new WebSocket(endpoint);
    const state = {id, tabId: tab.id, callKey: callIdentity(tab.url), ws, ready: false, googleReady: false, preparing: false, ending: false, endRequests: new Set(), automatic, accepted: false, keepalive: null, answerTimer: null, answerWake: null, answerWait: null, delivery: Promise.resolve()};
    current = state;
    status = "Đang kết nối relay và Google Live…";
    ws.onopen = () => {
      if (current !== state) return;
      ws.send(JSON.stringify({type: "auth", token: msg.token, capabilities: ["end_call"]}));
      state.keepalive = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type: "ping"}));
      }, 20000);
    };
    ws.onmessage = event => {
      if (current !== state) return;
      let data;
      try { data = JSON.parse(event.data); } catch { void stop("Relay trả dữ liệu chưa hợp lệ."); return; }
      if (data.type === "google_ready") {
        if (state.preparing) return;
        state.googleReady = true;
        wakeAnswer(state);
        state.preparing = true;
        state.delivery = state.delivery.then(async () => {
          if (current !== state) return;
          if (automatic) {
            if (!(await state.answerWait) || current !== state) return;
            await prepareAutomatic(state, automatic, revision);
          }
          if (current !== state) return;
          const result = await content(state, "start", {monitor: msg.monitor === true});
          if (current !== state) return;
          if (!result?.ok) { await stop(label(result)); return; }
          if (state.callKey) callTabs.set(state.tabId, {callKey: state.callKey, homeTabId: automatic?.tabId});
          state.ready = true;
          ws.send(JSON.stringify({type: "ready", ...(state.summaryPeer ? {summaryPeer: state.summaryPeer} : {}),
            ...(state.summaryIdentity ? {summaryIdentity: state.summaryIdentity} : {})}));
          status = "AI đang nghe và nói trong cuộc gọi này. Bấm Dừng AI để trả micro.";
        }).catch(() => { if (current === state) return stop("Không gắn được âm thanh; tải lại trang rồi gọi thử lại."); });
      } else if (data.type === "end_call") {
        void endCall(state, data.requestId, data.expiresAt);
      } else if (["audio", "clear"].includes(data.type)) {
        state.delivery = state.delivery.then(async () => {
          if (current === state && state.ready && !state.ending) {
            const result = await content(state, data.type, data);
            if (!result?.ok) throw new Error("BRIDGE");
          }
        }).catch(() => { if (current === state) return stop("Cầu nối âm thanh đã dừng; micro được trả lại."); });
      } else if (data.type === "error") {
        void stop(typeof data.message === "string" ? data.message.slice(0,250) : "Phiên Live đã dừng.");
      }
    };
    ws.onerror = () => { if (current === state) void stop("Không vào được relay. Kiểm tra lệnh call-lab và SSH tunnel."); };
    ws.onclose = () => { if (current === state) void stop("Relay đã đóng phiên; AI dừng và micro được trả lại."); };
    if (automatic) state.answerWait = waitForAutomatic(state, automatic, revision).catch(() => {
      if (current === state) return stop("Chưa xác nhận được cuộc gọi còn đổ chuông; AI không tự nhận.", {hangup: false}).then(() => false);
      return false;
    });
  } finally { if (attempt === revision) starting = false; }
}
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return;
  if (msg?.from === "call-lab-popup" && sender.url === chrome.runtime.getURL("popup.html")) {
    const action = msg.action === "start" ? start(msg) : msg.action === "takeover" ? takeover() : msg.action === "auto" ? saveAutomation(msg)
      : msg.action === "stop" ? stopAutomation() : automationReady;
    action.then(() => sendResponse({ok: true, status, active: !!current || starting, autoEnabled: automation.enabled,
      answerDelaySeconds: automation.answerDelaySeconds})).catch(error => {
      const notes = {
        ENDPOINT: "Địa chỉ cần là ws://127.0.0.1:8765 hoặc localhost qua SSH tunnel.",
        TOKEN: "Dán mã kết nối từ lệnh call-lab, không dán API key.",
        ACTIVE: "Đã có phiên AI. Bấm Dừng AI trước.",
        ANSWER_DELAY: "Thời gian chờ cần là số nguyên từ 0 đến 90 giây.",
      };
      status = notes[error.message] || "Chưa kết nối được tiện ích; tải lại trang Facebook rồi thử lại.";
      sendResponse({ok: false, status, active: !!current || starting});
    });
    return true;
  }
  if (msg?.from === "call-lab-content" && sender.tab && supported(sender.tab.url)) {
    if (msg.kind === "auto-register") {
      automationReady.then(() => sendResponse({watch: automation.enabled}));
      return true;
    }
    if (msg.kind === "incoming") {
      onIncoming(sender.tab.id, msg.ringId).then(() => sendResponse({ok: true})).catch(() => sendResponse({ok: false}));
      return true;
    }
    if (msg.kind === "call-ui") {
      onCallUI(sender.tab).then(() => sendResponse({ok: true})).catch(() => sendResponse({ok: false}));
      return true;
    }
  }
  if (msg?.from === "call-lab-content" && current && sender.tab?.id === current.tabId && msg.session === current.id) {
    if (msg.kind === "audio" && current.ready) {
      if (typeof msg.data !== "string" || msg.data.length > 9000 || msg.sampleRate !== 16000 || current.ws.bufferedAmount > 128000) {
        void stop("Đường truyền âm thanh bị dồn; đã trả micro.");
      } else if (current.ws.readyState === WebSocket.OPEN) {
        current.ws.send(JSON.stringify({type: "audio", data: msg.data, sampleRate: 16000}));
      }
    } else if (msg.kind === "error" || msg.kind === "ended") {
      void stop(msg.kind === "ended" ? "Kết nối cuộc gọi đã đóng; AI dừng." : label(msg), {hangup: msg.kind !== "ended"});
    }
    sendResponse({ok: true});
  }
});
chrome.tabs.onRemoved.addListener(tabId => {
  const wasCleaning = cleaning.has(tabId);
  cleaning.delete(tabId);
  const tracked = callTabs.get(tabId);
  callTabs.delete(tabId);
  const state = current?.tabId === tabId ? current : null;
  const ending = state ? stop("Tab gọi đã đóng; AI dừng.", {hangup: false}) : Promise.resolve();
  if (!wasCleaning && !tracked?.handedOff && (tracked || state?.callKey)) {
    void ending.then(() => refreshHome(tracked?.homeTabId ?? state?.automatic?.tabId));
  }
});
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.url || change.status === "loading") cleaning.delete(tabId);
  if (change.url || change.status === "loading") callTabs.delete(tabId);
  if ((change.url || change.status === "loading") && (supported(change.url) || supported(tab?.url))) refreshRevision++;
  if (current?.tabId === tabId && change.status === "loading") void stop("Trang đang tải lại; AI đã dừng.", {hangup: false});
  if (change.status === "complete" && supported(tab?.url)) {
    void automationReady.then(() => chrome.tabs.sendMessage(tabId,
      {to: "call-lab-content", command: "auto-watch", enabled: automation.enabled}, {frameId: 0})).catch(() => {});
  }
});
const automationReady = restoreAutomation();
