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
  function candidate() {
    const found = buttons().filter(button => {
      const name = label(button);
      if (!ANSWER.has(name)) return false;
      const scope = button.closest('[role="dialog"], [role="alertdialog"]') || button.parentElement?.parentElement;
      if (!scope) return false;
      const text = normalize(String(scope.textContent || "").slice(0, 4000));
      if (!INCOMING.test(text) || !buttons(scope).some(other => DECLINE.has(label(other)))) return false;
      if (/group call|cuộc gọi nhóm/.test(text)) return false;
      if (/video/.test(text) && !/audio|âm thanh/.test(name)) return false;
      return true;
    });
    return found.length === 1 ? found[0] : null;
  }
  let observed = null, ring = null, callback = null, observer = null, timer = null, interval = null;
  function scan() {
    timer = null;
    const button = candidate();
    if (!button) { observed = null; ring = null; return; }
    if (button === observed) return;
    observed = button;
    ring = crypto.randomUUID();
    callback?.({kind: "incoming", ringId: ring});
  }
  function watch(enabled, notify) {
    observer?.disconnect(); observer = null;
    clearTimeout(timer); clearInterval(interval); timer = interval = null;
    observed = ring = null; callback = enabled ? notify : null;
    if (!enabled) return;
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
  globalThis.CallLabIncoming = Object.freeze({watch, probe, accept, hangup});
})();
