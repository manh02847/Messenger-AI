/* Read-only caller metadata from the marked incoming-call card, in MAIN world. */
(() => {
  const ID = /^[1-9][0-9]{0,24}$/;
  const normalize = text => String(text || "").normalize("NFC").toLowerCase();
  const own = (object, key) => {
    try { return Object.getOwnPropertyDescriptor(object, key)?.value; } catch { return undefined; }
  };
  function numeric(value) {
    if (typeof value === "number" && Number.isSafeInteger(value)) value = String(value);
    return typeof value === "string" && ID.test(value) ? value : null;
  }
  function owner() {
    const ids = new Set();
    try {
      if (typeof globalThis.require === "function") {
        const value = numeric(own(globalThis.require("CurrentUserInitialData"), "USER_ID"));
        if (value) ids.add(value);
      }
    } catch {}
    try {
      for (const piece of String(document.cookie || "").split(";")) {
        const match = /^c_user=([1-9][0-9]{0,24})$/.exec(piece.trim());
        if (match) ids.add(match[1]);
      }
    } catch {}
    return ids.size === 1 ? [...ids][0] : null;
  }
  const CALLER_KEYS = new Set(["callerID", "callerId", "caller_id", "inviterID", "inviterId", "inviter_id"]);
  const PROFILE_KEYS = new Set(["actorID", "actorId", "userID", "userId", "profileID", "profileId"]);
  const PEOPLE_KEYS = new Set(["caller", "inviter", "actor", "profile", "user"]);
  const SKIP = new Set(["_owner", "return", "stateNode", "alternate", "ref", "current", "type", "onPress", "onClick"]);
  function read(ringId) {
    if (typeof ringId !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(ringId)) return {code: "RING_CHANGED"};
    const marked = [...document.querySelectorAll('[data-messenger-ai-ring]')]
      .filter(node => node.getAttribute("data-messenger-ai-ring") === ringId && node.isConnected);
    if (marked.length !== 1) return {code: "RING_CHANGED"};
    const button = marked[0];
    const scope = button.closest('[role="dialog"], [role="alertdialog"]') || button.parentElement?.parentElement;
    if (!scope || !/incoming (?:audio |voice |video )?call|is calling you|cuộc gọi (?:thoại |video )?đến|đang gọi (?:cho )?bạn/.test(normalize(scope.textContent))) return {code: "RING_CHANGED"};
    if (/group call|cuộc gọi nhóm/.test(normalize(scope.textContent))) return {code: "GROUP_CALL"};
    const ownerId = owner();
    if (!ownerId) return {code: "OWNER_ID_MISSING"};
    const nodes = [scope, ...scope.querySelectorAll("*")];
    if (nodes.length > 250) return {code: "CALL_CARD_TOO_LARGE"};
    const callers = new Set(), seen = [new Set(), new Set()];
    let remaining = 2000, incomplete = false, group = false;
    const add = value => { const id = numeric(value); if (id && id !== ownerId) callers.add(id); };
    function inspect(value, depth = 0, profiles = true) {
      const visited = seen[profiles ? 1 : 0];
      if (!value || typeof value !== "object" || visited.has(value)) return;
      if (depth > 10 || --remaining < 0) { incomplete = true; return; }
      visited.add(value);
      let descriptors;
      try { descriptors = Object.getOwnPropertyDescriptors(value); } catch { return; }
      if (Object.keys(descriptors).length > 200) { incomplete = true; return; }
      for (const [key, descriptor] of Object.entries(descriptors)) {
        if (!("value" in descriptor) || SKIP.has(key)) continue;
        const item = descriptor.value;
        if (["isGroupCall", "isGroup", "is_group"].includes(key) && item === true) group = true;
        if (["participants", "participantIDs", "participantIds"].includes(key) && Array.isArray(item)) {
          const participants = new Set(item.map(person => numeric(person) || numeric(own(person, "id"))).filter(Boolean));
          if (participants.size > 2) group = true;
        }
        if (CALLER_KEYS.has(key) || (profiles && PROFILE_KEYS.has(key))) add(item);
        if ((profiles && PEOPLE_KEYS.has(key)) || key === "caller" || key === "inviter") {
          for (const field of ["id", "ID", "fbid", "userID", "userId"]) add(own(item, field));
        }
        // Above the card, only explicitly named call objects are eligible.
        if (profiles || /^(?:call|incomingCall|callInfo|callData|invite|notification|payload|data)$/.test(key)) inspect(item, depth + 1, profiles);
      }
    }
    function profileLink(href) {
      if (typeof href !== "string" || href.length > 2048) return;
      try {
        const url = new URL(href, location.href);
        if (url.protocol !== "https:" || url.port || url.username || url.password
            || !["www.facebook.com", "web.facebook.com", "facebook.com", "m.facebook.com"].includes(url.hostname)) return;
        if (["/profile.php", "/ajax/hovercard/user.php"].includes(url.pathname) && url.searchParams.getAll("id").length === 1) add(url.searchParams.get("id"));
        else add(url.pathname.match(/^\/(?:people\/[^/]+\/)?([1-9][0-9]{0,24})\/?$/)?.[1]);
      } catch {}
    }
    for (const node of nodes) {
      for (const key of ["data-userid", "data-user-id", "data-profileid", "data-profile-id"]) add(node.getAttribute(key));
      profileLink(node.getAttribute("href"));
      profileLink(node.getAttribute("data-hovercard"));
      for (const key of Object.getOwnPropertyNames(node)) {
        if (key.startsWith("__reactProps$")) inspect(own(node, key));
        if (key.startsWith("__reactFiber$")) {
          let fiber = own(node, key);
          for (let i = 0; fiber && i < 40; i++, fiber = own(fiber, "return")) {
            const host = own(fiber, "stateNode");
            if (host && host !== scope && typeof host.nodeType === "number" && !scope.contains(host)) break;
            if (own(fiber, "tag") === 3) break;
            inspect(own(fiber, "memoizedProps"), 0, true);
            if (own(fiber, "stateNode") === scope) {
              fiber = own(fiber, "return");
              // A few call components may sit immediately above a portal/card.
              for (let j = 0; fiber && j < 4; j++, fiber = own(fiber, "return")) inspect(own(fiber, "memoizedProps"), 0, false);
              break;
            }
          }
        }
      }
    }
    if (group) return {code: "GROUP_CALL"};
    if (incomplete) return {code: "CALL_CARD_TOO_LARGE"};
    if (callers.size > 1) return {code: "CALLER_AMBIGUOUS"};
    if (!callers.size) return {code: "CALLER_ID_MISSING"};
    return {code: "RESOLVED", peer: {ownerId, callerId: [...callers][0]}};
  }
  globalThis.CallLabCaller = Object.freeze({read});
})();
