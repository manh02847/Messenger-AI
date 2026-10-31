/* Read-only caller metadata from the accepted call URL or marked call card. */
(() => {
  const ID = /^[1-9][0-9]{0,24}$/;
  const normalize = text => String(text || "").normalize("NFC").toLowerCase();
  const own = (object, key) => {
    try { return Object.getOwnPropertyDescriptor(object, key)?.value; } catch { return undefined; }
  };
  function numeric(value) {
    if (typeof value === "bigint") value = String(value);
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
  const SCHEMA_WORDS = new Set(("call calls caller callee peer peers other user users profile actor actors participant participants inviter initiator offer sender recipient party parties owner viewer local remote incoming outgoing current active previous pending notification payload data info dialog record records entity entities member members snapshot map by for source target session stream connection rtc media audio video thread room key keys id ids fb fbid facebook contact contacts name value values state context props memoized base next first last list node nodes size count total num is has get set ref _").split(" "));
  function schemaKey(key) {
    if (/^[0-9]+$/.test(key)) return "[]";
    const words = key.replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase().split(/_+/).filter(Boolean);
    return words.length && words.every(word => SCHEMA_WORDS.has(word)) && key.length <= 50
      && /^[A-Za-z_]+$/.test(key) ? key : "_";
  }
  function shape(value) {
    if (value === null) return "null";
    if (typeof value === "string") return /^[0-9]+$/.test(value) ? "numeric-string" : "string";
    if (value && typeof value === "object") {
      try { Map.prototype.has.call(value, null); return "map"; } catch {}
      try { Set.prototype.has.call(value, null); return "set"; } catch {}
    }
    return Array.isArray(value) ? "array" : typeof value;
  }
  function inspectCard(scope, source, expectedCall = "") {
    const diagnostics = {source, nodes: 0, props: 0, fibers: 0, hooks: 0, contexts: 0, maps: 0,
      roots: 0, walked: 0, matched: 0, reactTypes: [], fields: []};
    const fieldSet = new Set();
    function note(path, value) {
      const type = numeric(value)===ownerId ? "owner-id"
        : expectedCall && value===expectedCall ? "call-id" : shape(value), leaf = path.split(".").at(-1);
      if (path.length > 120 || diagnostics.fields.length >= 40
          || (!/(?:id|peer|participant|caller|callee|inviter|user|actor|profile|memoized|current)/i.test(leaf) && type !== "map" && type !== "set")) return;
      const item = path + "=" + type;
      if (!fieldSet.has(item)) { fieldSet.add(item); diagnostics.fields.push(item); }
    }
    const fail = code => {
      if (code === "CALL_CARD_TOO_LARGE" && !diagnostics.limit) diagnostics.limit = "metadata";
      const rank = field => /caller|callee|participant|inviter/i.test(field) ? 0 : /peer/i.test(field) ? 1 : /user.*id/i.test(field) ? 2 : 3;
      diagnostics.fields.sort((a,b)=>rank(a)-rank(b));
      return {code, diagnostics};
    };
    if (!scope) return fail("CALLER_ID_MISSING");
    if (/group call|cuộc gọi nhóm/.test(normalize(scope.textContent))) return fail("GROUP_CALL");
    const ownerId = owner();
    if (!ownerId) return fail("OWNER_ID_MISSING");
    const nodes = [scope, ...scope.querySelectorAll("*")];
    diagnostics.nodes = nodes.length;
    if (nodes.length > (source === "call" ? 1500 : 250)) return fail("CALL_CARD_TOO_LARGE");
    const callers = new Set(), seen = Array.from({length:4},()=>new Set()), fibers = new Set(), maps = new Set(), fallback = [];
    let remaining = 4000, incomplete = false, group = false, containerBranches = false;
    const add = value => { const id = numeric(value); if (id && id !== ownerId) callers.add(id); };
    function recordCall(value, path = "") {
      const values=["callID","callId","call_id"].map(key=>own(value,key));
      if(/\.(?:call|callInfo|callData|incomingCall)$/.test(path))values.push(own(value,"id"));
      return [...new Set(values.map(item=>typeof item==="number"&&Number.isSafeInteger(item)?String(item):item)
        .filter(item=>typeof item==="string"&&/^[A-Za-z0-9_-]{1,100}$/.test(item)))];
    }
    function entries(value) {
      if (Array.isArray(value)) {
        const size = own(value,"length");
        if (!Number.isInteger(size) || size > 32) return null;
        const result=[];
        for(let i=0;i<size;i++) {
          const entry=Object.getOwnPropertyDescriptor(value,String(i));
          if(!entry||!("value" in entry))return null;
          result.push([null,entry.value]);
        }
        return result;
      }
      try {
        const result = [];
        for (const pair of Map.prototype.entries.call(value)) {
          if (result.length >= 32) return null;
          result.push(pair);
        }
        return result;
      } catch { return []; }
    }
    function participants(value) {
      const rows = entries(value);
      if (rows === null) { incomplete = true; return; }
      if (rows.length > 2) { group = true; return; }
      if (rows.length !== 2) return;
      // A participant collection is useful only when it contains this verified
      // Facebook account as well as exactly one other numeric profile ID.
      const keys = rows.map(([key]) => numeric(key));
      let ids = keys.every(Boolean) && keys.includes(ownerId) ? keys : rows.map(([, item]) => {
        if (numeric(item)) return numeric(item);
        const values = [...new Set(["userID", "userId", "profileID", "fbid", "id"].map(key => numeric(own(item, key))).filter(Boolean))];
        return values.length === 1 ? values[0] : null;
      });
      if (ids.every(Boolean) && new Set(ids).size === 2 && ids.includes(ownerId)) ids.forEach(add);
    }
    function inspect(value, depth = 0, profiles = true, path = "props", proof = false) {
      const visited = seen[(profiles ? 2 : 0)+(proof ? 1 : 0)];
      if (!value || typeof value !== "object" || visited.has(value)) return;
      if (depth > 10 || --remaining < 0) { incomplete = true; return; }
      visited.add(value);
      const type=shape(value);
      if(type==="map"&&!maps.has(value)){maps.add(value);diagnostics.maps++;}
      if(type==="map"||type==="set")note(path,value);
      let descriptors;
      try { descriptors = Object.getOwnPropertyDescriptors(value); } catch { return; }
      if (Object.keys(descriptors).length > 200) { incomplete = true; return; }
      const calls=recordCall(value,path);
      if(expectedCall&&calls.length&&(calls.length!==1||calls[0]!==expectedCall))return;
      const currentCall=proof||!!(expectedCall&&calls.length===1&&calls[0]===expectedCall);
      for (const [key, descriptor] of Object.entries(descriptors)) {
        if (!("value" in descriptor)) continue;
        const item = descriptor.value;
        const nextPath = path + "." + schemaKey(key);
        note(nextPath, item);
        // The container fallback already finds rendered child fibers. Virtual
        // children may describe suspended/unmounted work and add deep duplicates.
        if (containerBranches && key === "children") continue;
        if (SKIP.has(key)) {
          if (key === "current" && /^(?:state|context)\./.test(path) && item && typeof item === "object") {
            let prototype;
            try {prototype=Object.getPrototypeOf(item);} catch {}
            // React refs may wrap call data; do not walk DOM/window objects.
            if (prototype === null || own(own(prototype,"constructor"),"name") === "Object") inspect(item,depth+1,false,nextPath,currentCall);
          }
          continue;
        }
        if (/^(?:prev|previous|history|historical|past|recent|cached|cache|oldCall|callHistory|contacts?|friends?)/i.test(key)) continue;
        if ((profiles||currentCall)&&["isGroupCall", "isGroup", "is_group"].includes(key) && item === true) group = true;
        if ((profiles||currentCall)&&/^(?:call)?participants?(?:ids|list|map)?$/.test(key.replaceAll("_", "").toLowerCase())) participants(item);
        if ((profiles||currentCall)&&CALLER_KEYS.has(key) || (profiles && PROFILE_KEYS.has(key))) add(item);
        if ((profiles && PEOPLE_KEYS.has(key)) || (currentCall&&(key === "caller" || key === "inviter"))) {
          for (const field of ["id", "ID", "fbid", "userID", "userId"]) add(own(item, field));
        }
        // Above the card, only explicitly named call objects are eligible.
        if (profiles || /^(?:state|context)(?:\.|$)/.test(path)
            || /^(?:call|incomingCall|callInfo|callData|invite|notification|payload|data|memoizedState|next|memoizedValue)$/.test(key)) inspect(item, depth + 1, profiles, nextPath,currentCall);
      }
    }
    function inspectFiber(fiber, profiles) {
      if (!fiber || fibers.has(fiber)) return;
      if (fibers.size >= 4000) {incomplete=true;return;}
      fibers.add(fiber);diagnostics.fibers++;
      const props = own(fiber, "memoizedProps");
      if (props) {diagnostics.props++;inspect(props, 0, profiles);}
      const state = own(fiber, "memoizedState");
      if (state) {diagnostics.hooks++;fallback.push([state, "state.memoizedState",false]);}
      let dependency = own(own(fiber, "dependencies"), "firstContext");
      for(let i=0;dependency&&i<16;i++,dependency=own(dependency,"next")) {
        const value = own(dependency,"memoizedValue");
        if(value) {diagnostics.contexts++;fallback.push([value,"context.memoizedValue",false]);}
      }
    }
    function inspectBranch(start, parentOf = fiber => own(fiber, "return")) {
      let fiber = start;
      for (let i = 0; fiber && i < 40; i++, fiber = parentOf(fiber)) {
        const host = own(fiber, "stateNode");
        if (host && host !== scope && typeof host.nodeType === "number" && !scope.contains(host)) break;
        if (own(fiber, "tag") === 3) break;
        inspectFiber(fiber, source === "ring");
        if (host === scope) {
          fiber = parentOf(fiber);
          for (let j = 0; fiber && j < 4 && own(fiber, "tag") !== 3; j++, fiber = parentOf(fiber)) inspectFiber(fiber, false);
          break;
        }
      }
    }
    function inspectContainers() {
      // React can store per-element fibers/props in private WeakMaps while
      // leaving only __reactContainer$ on the DOM. Locate the current tree,
      // then read metadata solely on branches rendering this exact call card.
      // Root props, sibling contacts, alternate and pending trees are excluded.
      const stop = limit => { diagnostics.limit = limit; incomplete = true; return false; };
      const elements = [document, ...document.querySelectorAll("*")];
      if (elements.length > 10000) { stop("dom"); return; }
      const roots = new Set();
      for (const element of elements) for (const key of Object.getOwnPropertyNames(element)) {
        if (!key.startsWith("__reactContainer$")) continue;
        if (!diagnostics.reactTypes.includes("container")) diagnostics.reactTypes.push("container");
        const anchor = own(element, key), root = own(anchor, "stateNode"), current = own(root, "current");
        if (own(anchor, "tag") !== 3 || own(current, "tag") !== 3
            || own(current, "stateNode") !== root || own(root, "containerInfo") !== element) continue;
        roots.add(current);
        if (roots.size > 16) { stop("roots"); return; }
      }
      diagnostics.roots = roots.size;
      const hosts = new Set(nodes), examined = new Set(), parents = new Map(), matched = [];
      const now = () => globalThis.performance?.now?.() ?? Date.now();
      const deadline = now() + 250;
      function withinBudget(fiber, phase) {
        if (now() > deadline) return stop("time");
        if (!examined.has(fiber) && examined.size >= 50000) return stop(phase);
        examined.add(fiber);
        diagnostics.walked = examined.size;
        return true;
      }
      function children(fiber, queue, discovered, phase) {
        for (let child = own(fiber, "child"); child; child = own(child, "sibling")) {
          if (typeof child !== "object") return stop("tree");
          if (discovered.has(child)) return stop("cycle");
          if (discovered.size >= 50000) return stop(phase);
          if (now() > deadline) return stop("time");
          discovered.add(child);
          parents.set(child, fiber);
          queue.push(child);
        }
        return true;
      }
      const queue = [...roots], discovered = new Set(roots);
      for (const root of roots) parents.set(root, null);
      const addMatch = fiber => { matched.push(fiber); diagnostics.matched = matched.length; };
      let card = null;
      // Breadth-first search reaches overlays before spending the budget deep
      // in the feed. Do not read any page-wide metadata while locating the card.
      for (let head = 0; head < queue.length; head++) {
        const fiber = queue[head];
        if (!withinBudget(fiber, "search")) return;
        if (source === "ring" && own(fiber, "stateNode") === scope) { card = fiber; break; }
        if (source === "call" && hosts.has(own(fiber, "stateNode"))) addMatch(fiber);
        if (!children(fiber, queue, discovered, "search")) return;
      }
      if (source === "ring") {
        if (!card) return;
        // Finding the exact marked card ends the page-wide search. Complete
        // only its current subtree so conflicting people in the card are still
        // detected, regardless of the size of unrelated page branches.
        const branch = [card], branchSeen = new Set(branch);
        for (let head = 0; head < branch.length; head++) {
          const fiber = branch[head];
          if (!withinBudget(fiber, "branch")) return;
          if (hosts.has(own(fiber, "stateNode"))) addMatch(fiber);
          if (!children(fiber, branch, branchSeen, "branch")) return;
        }
      }
      // Read identities only after the selected subtree has been fully checked.
      containerBranches = true;
      for (const fiber of matched) inspectBranch(fiber, item => parents.get(item));
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
      if (source === "ring") {
        for (const key of ["data-userid", "data-user-id", "data-profileid", "data-profile-id"]) add(node.getAttribute(key));
        profileLink(node.getAttribute("href"));
        profileLink(node.getAttribute("data-hovercard"));
      }
      for (const key of Object.getOwnPropertyNames(node)) {
        if (/^__react/i.test(key)) {
          const kind = key.startsWith("__reactProps$") ? "props" : key.startsWith("__reactFiber$") ? "fiber"
            : key.startsWith("__reactInternalInstance$") ? "internal" : key.startsWith("__reactContainer$") ? "container" : "other";
          if (!diagnostics.reactTypes.includes(kind)) diagnostics.reactTypes.push(kind);
        }
        if (key.startsWith("__reactProps$")) {diagnostics.props++;inspect(own(node, key),0,source==="ring");}
        if (key.startsWith("__reactFiber$")) {
          inspectBranch(own(node, key));
        }
      }
    }
    if (!callers.size && !group && !fibers.size) inspectContainers();
    if (!callers.size && !group) for (const [value,path,proof] of fallback) inspect(value, 0, false, path,proof);
    if (group) return fail("GROUP_CALL");
    if (incomplete) return fail("CALL_CARD_TOO_LARGE");
    if (callers.size > 1) return fail("CALLER_AMBIGUOUS");
    if (!callers.size) return fail("CALLER_ID_MISSING");
    return {code: "RESOLVED", peer: {ownerId, callerId: [...callers][0]}};
  }
  function read(ringId) {
    if (typeof ringId !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(ringId)) return {code: "RING_CHANGED"};
    const marked = [...document.querySelectorAll('[data-messenger-ai-ring]')]
      .filter(node => node.getAttribute("data-messenger-ai-ring") === ringId && node.isConnected);
    if (marked.length !== 1) return {code: "RING_CHANGED"};
    const button = marked[0];
    const scope = button.closest('[role="dialog"], [role="alertdialog"]') || button.parentElement?.parentElement;
    if (!scope || !/incoming (?:audio |voice |video )?call|is calling you|cuộc gọi (?:thoại |video )?đến|đang gọi (?:cho )?bạn/.test(normalize(scope.textContent))) return {code: "RING_CHANGED"};
    return inspectCard(scope, "ring");
  }
  function readActive(callKey) {
    try {
      const url = new URL(location.href);
      if (url.protocol !== "https:" || url.port || url.username || url.password
          || !["www.facebook.com", "web.facebook.com", "www.messenger.com", "messenger.com"].includes(url.hostname)
          || !/^\/(?:groupcall|call|calls)(?:\/|$)/.test(url.pathname)
          || url.searchParams.getAll("call_id").length !== 1
          || !/^[A-Za-z0-9_-]{1,100}$/.test(url.searchParams.get("call_id") || "")
          || callKey !== url.origin + url.pathname + "?call_id=" + (url.searchParams.get("call_id") || "")) return {code: "RING_CHANGED"};
      const query = url.searchParams, types = query.getAll("thread_type");
      if (types.length > 1) return {code: "INVALID_PEER"};
      // Thread types are the same pinned one-to-one/group enum as the native
      // bridge. ROOM and call_id identify a call, never a person's account.
      if (["2", "8", "11", "16"].includes(types[0])) return {code: "GROUP_CALL"};
      if (types.length && !["1", "7", "13", "15"].includes(types[0])) return {code: "INVALID_PEER"};
      if (query.has("peer_id") || query.has("av")) {
        if (query.getAll("peer_id").length !== 1 || query.getAll("av").length !== 1
            || !["1", "7", "13", "15"].includes(types[0])) return {code: "INVALID_PEER"};
        const callerId = numeric(query.get("peer_id")), viewer = numeric(query.get("av"));
        if (!callerId || !viewer || callerId === viewer) return {code: "INVALID_PEER"};
        const ownerId = owner();
        if (!ownerId) return {code: "OWNER_ID_MISSING"};
        if (viewer !== ownerId) return {code: "OWNER_MISMATCH"};
        return {code: "RESOLVED", peer: {ownerId, callerId}, method: "call-url"};
      }
      return inspectCard(document.body, "call",url.searchParams.get("call_id"));
    } catch { return {code: "RING_CHANGED"}; }
  }
  globalThis.CallLabCaller = Object.freeze({read, readActive});
})();
