/* Runs in the isolated extension world. No message text leaves this script. */
(() => {
  const normalize = value => String(value || "").normalize("NFC").trim().toLowerCase().replace(/\s+/g, " ");
  const ANSWER = new Set(["accept", "answer", "accept call", "answer call", "answer audio call", "accept audio call",
    "chấp nhận", "trả lời", "nhận cuộc gọi", "chấp nhận cuộc gọi", "trả lời cuộc gọi", "nhận cuộc gọi thoại", "trả lời bằng âm thanh"]);
  const DECLINE = new Set(["decline", "decline call", "decline audio call", "reject call", "từ chối", "từ chối cuộc gọi", "từ chối cuộc gọi thoại"]);
  const END = new Set(["end call", "hang up", "hangup", "kết thúc cuộc gọi", "gác máy"]);
  const INCOMING = /incoming (?:audio |voice |video )?call|is calling you|cuộc gọi (?:thoại |video )?đến|đang gọi (?:cho )?bạn/;
  const label = button => normalize(button.getAttribute("aria-label") || button.getAttribute("title") || button.innerText);
  function visible(button) {
    const style = getComputedStyle(button), box = button.getBoundingClientRect();
    return button.isConnected && !button.disabled && button.getAttribute("aria-disabled") !== "true"
      && style.display !== "none" && style.visibility !== "hidden" && box.width > 0 && box.height > 0;
  }
  function buttons(root = document) {
    return [...root.querySelectorAll('button, [role="button"]')].filter(visible);
  }
  function candidates(forAnswer = true) {
    return buttons().filter(button => {
      const name = label(button);
      if (!ANSWER.has(name)) return false;
      const scope = button.closest('[role="dialog"], [role="alertdialog"]') || button.parentElement?.parentElement;
      if (!scope) return false;
      const text = normalize(String(scope.textContent || "").slice(0, 4000));
      if (!INCOMING.test(text) || !buttons(scope).some(other => DECLINE.has(label(other)))) return false;
      if (forAnswer && /group call|cuộc gọi nhóm/.test(text)) return false;
      if (forAnswer && /video/.test(text) && !/audio|âm thanh/.test(name)) return false;
      return true;
    });
  }
  function candidate() {
    const found = candidates();
    return found.length === 1 ? found[0] : null;
  }
  function endState() {
    const path = globalThis.location?.pathname || "";
    const callPage = /^\/(?:groupcall|call|calls)(?:\/|$)/.test(path);
    const names = buttons().map(label);
    const busy = names.some(name => END.has(name)) || candidates(false).length > 0
      || (callPage && names.some(name => ANSWER.has(name) || DECLINE.has(name)));
    // A stale rating panel must not close a new active or ringing call.
    if (!callPage || busy) return {ended: false, handoff: false, busy};
    const text = normalize(String(document.body?.innerText || "").slice(0, 20000));
    const handoff = /answered (?:this call )?on another device|đã (?:được )?trả lời (?:cuộc gọi này )?trên thiết bị khác/.test(text);
    const close = names.some(name => ["close", "đóng"].includes(name));
    const redial = names.some(name => ["call again", "call back", "redial", "gọi lại"].includes(name));
    const ended = close && (redial || handoff || /bạn thấy chất lượng cuộc gọi|how was (?:the quality of )?your call|cuộc gọi (?:đã )?kết thúc|call (?:has )?ended/.test(text));
    return {ended, handoff, busy};
  }
  let observed = null, ring = null, callback = null, observer = null, timer = null, interval = null;
  let autoEnabled = false, lastUI = "";
  function scan() {
    timer = null;
    const ui = endState();
    const marker = JSON.stringify(ui);
    if (marker !== lastUI || ui.ended) {
      lastUI = marker;
      if (ui.ended || ui.handoff) callback?.({kind: "call-ui"});
    }
    if (!autoEnabled) return;
    const button = candidate();
    if (!button) { observed = null; ring = null; return; }
    if (button === observed) return;
    observed = button;
    ring = crypto.randomUUID();
    callback?.({kind: "incoming", ringId: ring});
  }
  function watch(enabled, notify) {
    callback = notify;
    // A dormant worker restores its saved mode while the first incoming event
    // is still being handled. Keep that event's nonce valid across rearming.
    if (observer && autoEnabled === enabled) return;
    observer?.disconnect(); observer = null;
    clearTimeout(timer); clearInterval(interval); timer = interval = null;
    observed = ring = null; autoEnabled = enabled; lastUI = "";
    observer = new MutationObserver(() => { if (!timer) timer = setTimeout(scan, 350); });
    observer.observe(document, {subtree: true, childList: true, attributes: true, attributeFilter: ["aria-label", "title", "style", "disabled", "aria-disabled"]});
    interval = setInterval(scan, 2500);
    scan();
  }
  function probe() {
    // Revalidate the same live button; a removed/replaced dialog needs a new nonce.
    return {ok: true, ringId: ring && observed === candidate() ? ring : null};
  }
  function accept(id) {
    if (!id || id !== probe().ringId) return {ok: false};
    const button = observed;
    observed = ring = null;
    button.click();
    return {ok: true, accepted: true};
  }
  function hangup() {
    const found = buttons().filter(button => END.has(label(button)));
    if (found.length !== 1) return {ok: false};
    found[0].click();
    return {ok: true};
  }
  globalThis.CallLabIncoming = Object.freeze({watch, probe, accept, hangup, endState});
})();
