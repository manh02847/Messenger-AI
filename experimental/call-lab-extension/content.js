(() => {
  const CHANNEL = "messenger-ai-call-lab-v1";
  const pending = new Map();
  let session = null;
  function main(command, details) {
    const requestId = crypto.randomUUID();
    return new Promise(resolve => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        resolve({ok: false, code: "BRIDGE_NOT_READY"});
      }, command === "start" || command === "stop" ? 5000 : 1500);
      pending.set(requestId, result => { clearTimeout(timer); resolve(result); });
      window.postMessage({channel: CHANNEL, direction: "command", command, requestId, session: session || "probe", ...details}, location.origin);
    });
  }
  window.addEventListener("message", event => {
    const msg = event.data;
    if (event.source !== window || !msg || msg.channel !== CHANNEL || msg.direction !== "event") return;
    if (msg.kind === "reply") {
      const resolve = pending.get(msg.requestId);
      if (resolve) { pending.delete(msg.requestId); resolve(msg); }
    } else if (session && msg.session === session && ["audio", "error", "ended"].includes(msg.kind)) {
      chrome.runtime.sendMessage({from: "call-lab-content", ...msg}).catch(() => {
        void main("stop", {});
        session = null;
      });
    }
  });
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id || msg?.to !== "call-lab-content") return;
    if (msg.command === "start") session = msg.session;
    if (msg.command !== "probe" && msg.session !== session) {
      sendResponse({ok: false, code: "SESSION_CHANGED"});
      return;
    }
    main(msg.command, msg).then(result => {
      if (msg.command === "stop" && session === msg.session) session = null;
      sendResponse(result);
    });
    return true;
  });
})();
