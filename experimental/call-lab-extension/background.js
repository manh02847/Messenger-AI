let current = null;
let starting = false;
let attempt = 0;
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
async function stop(text = "Đã dừng AI và trả lại micro cho cuộc gọi.") {
  attempt++;
  starting = false;
  const state = current;
  current = null;
  status = text;
  if (!state) return;
  clearInterval(state.keepalive);
  try { if (state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({type: "stop"})); } catch {}
  try { state.ws.close(); } catch {}
  try { await content(state, "stop"); } catch {}
}
async function start(msg) {
  if (current || starting) throw new Error("ACTIVE");
  const endpoint = endpointURL(msg.endpoint);
  if (typeof msg.token !== "string" || msg.token.length < 20 || msg.token.length > 200) throw new Error("TOKEN");
  const revision = ++attempt;
  starting = true;
  try {
    status = "Đang tìm cuộc gọi trong các cửa sổ Facebook/Messenger…";
    const id = crypto.randomUUID();
    const found = await findCall(revision, id);
    if (found.cancelled || attempt !== revision) return;
    if (!found.tab) { status = label(found); return; }
    const tab = found.tab;
    await chrome.storage.session.set({endpoint, token: msg.token, monitor: msg.monitor === true});
    if (attempt !== revision) return;
    const ws = new WebSocket(endpoint);
    const state = {id, tabId: tab.id, ws, ready: false, keepalive: null, delivery: Promise.resolve()};
    current = state;
    status = "Đang kết nối relay và Google Live…";
    ws.onopen = () => {
      if (current !== state) return;
      ws.send(JSON.stringify({type: "auth", token: msg.token}));
      state.keepalive = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type: "ping"}));
      }, 20000);
    };
    ws.onmessage = event => {
      if (current !== state) return;
      let data;
      try { data = JSON.parse(event.data); } catch { void stop("Relay trả dữ liệu chưa hợp lệ."); return; }
      if (data.type === "google_ready") {
        state.delivery = state.delivery.then(async () => {
          if (current !== state) return;
          const result = await content(state, "start", {monitor: msg.monitor === true});
          if (current !== state) return;
          if (!result?.ok) { await stop(label(result)); return; }
          state.ready = true;
          ws.send(JSON.stringify({type: "ready"}));
          status = "AI đang nghe và nói trong cuộc gọi này. Bấm Dừng AI để trả micro.";
        }).catch(() => { if (current === state) return stop("Không gắn được âm thanh; tải lại trang rồi gọi thử lại."); });
      } else if (["audio", "clear"].includes(data.type)) {
        state.delivery = state.delivery.then(async () => {
          if (current === state && state.ready) {
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
  } finally { if (attempt === revision) starting = false; }
}
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return;
  if (msg?.from === "call-lab-popup" && sender.url === chrome.runtime.getURL("popup.html")) {
    const action = msg.action === "start" ? start(msg) : msg.action === "stop" ? stop() : Promise.resolve();
    action.then(() => sendResponse({ok: true, status, active: !!current || starting})).catch(error => {
      const notes = {
        ENDPOINT: "Địa chỉ cần là ws://127.0.0.1:8765 hoặc localhost qua SSH tunnel.",
        TOKEN: "Dán mã kết nối từ lệnh call-lab, không dán API key.",
        ACTIVE: "Đã có phiên thử. Bấm Dừng AI trước.",
      };
      status = notes[error.message] || "Chưa kết nối được tiện ích; tải lại trang Facebook rồi thử lại.";
      sendResponse({ok: false, status, active: !!current || starting});
    });
    return true;
  }
  if (msg?.from === "call-lab-content" && current && sender.tab?.id === current.tabId && msg.session === current.id) {
    if (msg.kind === "audio" && current.ready) {
      if (typeof msg.data !== "string" || msg.data.length > 9000 || msg.sampleRate !== 16000 || current.ws.bufferedAmount > 128000) {
        void stop("Đường truyền âm thanh bị dồn; đã trả micro.");
      } else if (current.ws.readyState === WebSocket.OPEN) {
        current.ws.send(JSON.stringify({type: "audio", data: msg.data, sampleRate: 16000}));
      }
    } else if (msg.kind === "error" || msg.kind === "ended") {
      void stop(msg.kind === "ended" ? "Cuộc gọi đã kết thúc; AI dừng." : label(msg));
    }
    sendResponse({ok: true});
  }
});
chrome.tabs.onRemoved.addListener(tabId => { if (current?.tabId === tabId) void stop("Tab gọi đã đóng; AI dừng."); });
chrome.tabs.onUpdated.addListener((tabId, change) => { if (current?.tabId === tabId && change.status === "loading") void stop("Trang đang tải lại; AI đã dừng."); });
