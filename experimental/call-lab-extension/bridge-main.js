/* Passive until the user presses Start. No cookie, DOM message or key access. */
(() => {
  if (window.__messengerCallLabInstalled) return;
  window.__messengerCallLabInstalled = true;
  const CHANNEL = "messenger-ai-call-lab-v1";
  const connections = new Set();
  let active = null;
  let transition = 0;
  let teardown = Promise.resolve();

  function emit(kind, details = {}) {
    window.postMessage({channel: CHANNEL, direction: "event", kind, ...details}, location.origin);
  }
  function candidates() {
    return [...connections].filter(pc => {
      try {
        return pc.connectionState === "connected"
          && pc.getReceivers().some(r => r.track?.kind === "audio" && r.track.readyState === "live")
          && pc.getSenders().some(s => s.track?.kind === "audio" && s.track.readyState === "live");
      } catch { return false; }
    });
  }
  const Native = window.RTCPeerConnection;
  if (Native) {
    window.RTCPeerConnection = new Proxy(Native, {
      construct(target, args, newTarget) {
        const pc = Reflect.construct(target, args, newTarget);
        connections.add(pc);
        pc.addEventListener("connectionstatechange", () => {
          if (["closed", "failed"].includes(pc.connectionState)) {
            connections.delete(pc);
            if (active?.pc === pc) {
              const session = active.session;
              void stop().then(() => emit("ended", {session}));
            }
          }
        });
        return pc;
      }
    });
  }

  function clearAudio(state = active) {
    if (!state) return;
    for (const source of state.sources) {
      try { source.stop(); } catch {}
    }
    state.sources.clear();
    state.nextTime = state.context.currentTime;
  }
  async function dispose(state) {
    if (!state) return teardown;
    if (!state.cleanup) {
      const previous = teardown;
      state.cleanup = (async () => {
        await previous;
        clearAudio(state);
        if (state.processor) state.processor.onaudioprocess = null;
        for (const node of state.nodes) {
          try { node.disconnect(); } catch {}
        }
        for (const [sender, original] of state.originals) {
          try { await sender.replaceTrack(original.readyState === "live" ? original : null); } catch {}
        }
        for (const track of state.destination.stream.getTracks()) track.stop();
        try { await state.context.close(); } catch {}
      })();
      teardown = state.cleanup.catch(() => {});
    }
    await state.cleanup;
  }
  async function stop() {
    transition++;
    const state = active;
    active = null;
    await dispose(state);
  }

  async function start(session, monitor) {
    const revision = ++transition;
    const previous = active;
    active = null;
    await dispose(previous);
    if (revision !== transition) throw new Error("CANCELLED");
    const choices = candidates();
    if (choices.length !== 1) throw new Error(choices.length ? "MULTIPLE_CALLS" : "NO_CALL");
    const pc = choices[0];
    const senders = pc.getSenders().filter(s => s.track?.kind === "audio");
    const remote = pc.getReceivers().filter(r => r.track?.kind === "audio").map(r => r.track);
    if (senders.length !== 1 || remote.length !== 1) throw new Error("MULTIPLE_CALLS");
    const context = new AudioContext();
    const destination = context.createMediaStreamDestination();
    const state = {
      session, pc, context, destination, sources: new Set(), nextTime: 0,
      originals: senders.map(sender => [sender, sender.track]), nodes: [], processor: null,
    };
    active = state;
    try {
      await context.resume();
      if (active !== state) throw new Error("CANCELLED");
      if (context.state !== "running") throw new Error("AUDIO_PERMISSION");
      const source = context.createMediaStreamSource(new MediaStream(remote));
      // A fixed local ScriptProcessor keeps this prototype independent of a
      // site's AudioWorklet module/CSP loading rules. It is not a recorder.
      const processor = context.createScriptProcessor(4096, 1, 1);
      const silent = context.createGain();
      silent.gain.value = 0;
      const resampler = new CallLabPCM.Resampler(context.sampleRate);
      state.processor = processor;
      state.nodes.push(source, processor, silent);
      processor.onaudioprocess = event => {
        if (active !== state) return;
        const samples = resampler.push(event.inputBuffer.getChannelData(0));
        for (let offset = 0; offset < samples.length; offset += 1600) {
          emit("audio", {session, data: CallLabPCM.encode(samples.subarray(offset, offset + 1600)), sampleRate: 16000});
        }
      };
      source.connect(processor);
      processor.connect(silent).connect(context.destination);
      state.monitor = monitor;
      for (const sender of senders) {
        if (active !== state) throw new Error("CANCELLED");
        await sender.replaceTrack(destination.stream.getAudioTracks()[0]);
      }
      if (active !== state) throw new Error("CANCELLED");
    } catch (error) {
      const cancelled = revision !== transition;
      if (active === state) active = null;
      await dispose(state);
      throw cancelled ? new Error("CANCELLED") : error;
    }
  }

  function play(data) {
    const state = active;
    if (!state || typeof data !== "string" || data.length > 512000) return;
    const samples = CallLabPCM.decode(data);
    const now = state.context.currentTime;
    if (Math.max(now, state.nextTime) - now + samples.length / 24000 > 30) throw new Error("AUDIO_BACKLOG");
    const buffer = state.context.createBuffer(1, samples.length, 24000);
    buffer.getChannelData(0).set(samples);
    const source = state.context.createBufferSource();
    source.buffer = buffer;
    source.connect(state.destination);
    if (state.monitor) source.connect(state.context.destination);
    source.onended = () => state.sources.delete(source);
    state.sources.add(source);
    state.nextTime = Math.max(now + 0.015, state.nextTime);
    source.start(state.nextTime);
    state.nextTime += buffer.duration;
  }

  window.addEventListener("message", async event => {
    const msg = event.data;
    if (event.source !== window || !msg || msg.channel !== CHANNEL || msg.direction !== "command") return;
    if (typeof msg.requestId !== "string" || typeof msg.session !== "string") return;
    try {
      if (msg.command === "probe") {
        emit("reply", {requestId: msg.requestId, ok: true, count: candidates().length});
        return;
      }
      if (msg.command === "start") await start(msg.session, msg.monitor === true);
      else if (msg.command === "stop") {
        if (!active || active.session === msg.session) await stop();
      } else if (active?.session === msg.session) {
        if (msg.command === "clear") clearAudio();
        else if (msg.command === "audio") play(msg.data);
        else return;
      } else if (msg.command !== "stop") return;
      emit("reply", {requestId: msg.requestId, ok: true});
    } catch (error) {
      const allowed = ["NO_CALL", "MULTIPLE_CALLS", "AUDIO_PERMISSION", "AUDIO_BACKLOG", "CANCELLED"];
      const code = allowed.includes(error.message) ? error.message : "AUDIO_BRIDGE_FAILED";
      if (msg.command !== "start" && active?.session === msg.session) await stop();
      emit("reply", {requestId: msg.requestId, ok: false, code});
      emit("error", {session: msg.session, code});
    }
  });
})();
