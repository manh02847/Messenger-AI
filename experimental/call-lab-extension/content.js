(() => {
  const CHANNEL = "messenger-ai-call-lab-v1";
  const pending = new Map();
  let session = null;
  function matchesCall(key) {
    if (!key) return true;
    const url = new URL(location.href);
    return key === url.origin + url.pathname + "?call_id=" + (url.searchParams.get("call_id") || "");
  }
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
  async function incomingIdentity(incoming, ringId) {
    if (!incoming.mark || !incoming.mark(ringId)) return {ok: false};
    const captured = await main("incoming-peer", {ringId});
    if (incoming.probe().ringId !== ringId) return {ok: false};
    const known = new Set(["RESOLVED", "RING_CHANGED", "GROUP_CALL", "OWNER_ID_MISSING",
      "CALL_CARD_TOO_LARGE", "CALLER_AMBIGUOUS", "CALLER_ID_MISSING", "MAIN_BRIDGE_MISSING"]);
    const code = known.has(captured.identity?.code) ? captured.identity.code : "MAIN_BRIDGE_MISSING";
    const peer = code === "RESOLVED" ? captured.identity.peer : null;
    // Return only bounded numeric identifiers; never forward page objects.
    const valid = peer && Object.keys(peer).length === 2
      && [peer.ownerId, peer.callerId].every(value => typeof value === "string" && /^[1-9][0-9]{0,24}$/.test(value))
      && peer.ownerId !== peer.callerId;
    return {ok: true, ringId, ...(valid ? {summaryPeer: {ownerId: peer.ownerId, callerId: peer.callerId}} : {}),
      summaryIdentity: {version: "0.6.1", code: valid ? "RESOLVED" : code === "RESOLVED" ? "INVALID_PEER" : code}};
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
    if (msg.command === "ui-probe") {
      main("probe", {}).then(result => sendResponse({ok: result.ok === true,
        count: result.count, ...globalThis.CallLabIncoming?.endState()}));
      return true;
    }
    if (typeof msg.command !== "string") return;
    if (msg.command.startsWith("auto-")) {
      const incoming = globalThis.CallLabIncoming;
      if (!incoming) { sendResponse({ok: false, code: "AUTO_NOT_READY"}); return; }
      if (msg.command === "auto-watch") {
        incoming.watch(msg.enabled === true, details => chrome.runtime.sendMessage({from: "call-lab-content", ...details}).catch(() => {}));
        sendResponse({ok: true});
      } else if (msg.command === "auto-probe") sendResponse(incoming.probe());
      else if (msg.command === "auto-identity") {
        incomingIdentity(incoming, msg.ringId).then(sendResponse).catch(() => sendResponse({ok: false}));
        return true;
      }
      else if (msg.command === "auto-accept") sendResponse(incoming.accept(msg.ringId));
      else if (msg.command === "auto-hangup" && session === msg.session) sendResponse(incoming.hangup());
      else sendResponse({ok: false});
      return;
    }
    if (msg.command === "start") session = msg.session;
    if (msg.command !== "probe" && msg.session !== session) {
      sendResponse({ok: false, code: "SESSION_CHANGED"});
      return;
    }
    if (msg.command === "end-call") {
      const selected = session;
      main("hangup-check", {session: selected}).then(result => {
        try {
          const incoming = globalThis.CallLabIncoming;
          if (!result.ok || !Number.isFinite(msg.expiresAt) || Date.now() >= msg.expiresAt
              || session !== selected || msg.session !== session || !matchesCall(msg.callKey)
              || !incoming || incoming.endState().handoff) { sendResponse({ok: false}); return; }
          sendResponse(incoming.hangup());
        } catch { sendResponse({ok: false}); }
      });
      return true;
    }
    main(msg.command, msg).then(result => {
      if (msg.command === "stop" && session === msg.session) session = null;
      sendResponse(result);
    });
    return true;
  });
  if (globalThis.CallLabIncoming) {
    chrome.runtime.sendMessage({from: "call-lab-content", kind: "auto-register"}).then(result => {
      globalThis.CallLabIncoming.watch(result?.watch === true, details => chrome.runtime.sendMessage({from: "call-lab-content", ...details}).catch(() => {}));
    }).catch(() => {});
  }
})();
