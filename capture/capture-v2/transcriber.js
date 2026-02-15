// =============================================================================
// transcriber.js — MAIN WORLD automatic media transcription engine
// =============================================================================
// Design goals:
//   1) Automatic start/stop tied to media playback (no manual click required)
//   2) Prefer direct media audio track input when supported:
//        recognition.start(mediaTrack)
//   3) Fallback to default microphone when direct track is unavailable
//   4) Stable operation on SPAs (especially YouTube)
//   5) Clear, minimal message protocol to content.js for transcript saving
// =============================================================================

(() => {
  "use strict";

  if (window.__transcriber_main_world_loaded) return;
  window.__transcriber_main_world_loaded = true;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    window.postMessage({
      source: "transcriber_main_world",
      type: "transcript_unavailable",
      message: "SpeechRecognition API not available",
    }, "*");
    return;
  }

  const CONFIG = {
    lang: "en-US",
    interimResults: true,
    continuous: true,
    maxAlternatives: 1,
    restartDelayMs: 300,
    maxConsecutiveRestarts: 60,
    periodicEmitMs: 15000,
    noSpeechWarnEvery: 10,
    autoplayPollMs: 1500,
    youtubeUrlCheckMs: 1000,
    preferDirectMediaTrack: true,
    log: true,
  };

  const IS_YOUTUBE = /(^|\.)youtube\.com$/i.test(location.hostname) || /(^|\.)youtu\.be$/i.test(location.hostname);

  /** @type {WeakMap<HTMLMediaElement, any>} */
  const states = new WeakMap();

  let lastKnownUrl = location.href;

  function post(type, payload = {}) {
    window.postMessage({
      source: "transcriber_main_world",
      type,
      ...payload,
    }, "*");
  }

  function log(...args) {
    if (CONFIG.log) console.log("[Transcriber]", ...args);
  }

  function warn(...args) {
    console.warn("[Transcriber]", ...args);
  }

  function nowStamp() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
  }

  function mediaTitle(media) {
    return (
      media.title ||
      media.getAttribute("aria-label") ||
      document.title ||
      location.hostname ||
      "media"
    ).substring(0, 120);
  }

  function getState(media) {
    if (states.has(media)) return states.get(media);

    const s = {
      id: `m_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      recognition: null,
      active: false,
      permissionDenied: false,
      inputMode: "unknown", // media-track | microphone
      transcript: [],
      lastEmittedIndex: 0,
      saveCount: 0,
      restartCount: 0,
      noSpeechStreak: 0,
      periodicTimer: null,
      attached: false,
      playbackStream: null,
      playbackTrack: null,
      startedAt: Date.now(),
    };

    states.set(media, s);
    return s;
  }

  function tryGetMediaTrack(media) {
    try {
      const capture = media.captureStream || media.mozCaptureStream;
      if (typeof capture !== "function") return null;

      const stream = capture.call(media);
      const track = stream?.getAudioTracks?.()[0] || null;
      if (!track) return null;

      return { stream, track };
    } catch (err) {
      warn("captureStream unavailable:", err?.message || err);
      return null;
    }
  }

  function startEngine(recognition, media, state) {
    if (CONFIG.preferDirectMediaTrack) {
      const captured = tryGetMediaTrack(media);
      if (captured?.track) {
        try {
          recognition.start(captured.track);
          state.playbackStream = captured.stream;
          state.playbackTrack = captured.track;
          state.inputMode = "media-track";
          log("SR started with media-track input.");
          return;
        } catch (err) {
          warn("start(track) failed, fallback to microphone:", err?.message || err);
        }
      }
    }

    recognition.start();
    state.inputMode = "microphone";
    log("SR started with microphone input.");
  }

  function emitPeriodicSnapshot(media, state) {
    if (!state.active) return;
    if (state.transcript.length <= state.lastEmittedIndex) return;

    state.saveCount += 1;
    const newLines = state.transcript.slice(state.lastEmittedIndex);
    state.lastEmittedIndex = state.transcript.length;

    post("transcript_periodic", {
      mediaId: state.id,
      title: mediaTitle(media),
      transcript: [...state.transcript],
      newLines,
      lineCount: state.transcript.length,
      saveNumber: state.saveCount,
      inputMode: state.inputMode,
      url: location.href,
    });
  }

  function startPeriodicEmitter(media, state) {
    clearInterval(state.periodicTimer);
    state.periodicTimer = setInterval(() => emitPeriodicSnapshot(media, state), CONFIG.periodicEmitMs);
  }

  function stopPeriodicEmitter(state) {
    clearInterval(state.periodicTimer);
    state.periodicTimer = null;
  }

  function startRecognition(media, reason = "playback") {
    const state = getState(media);
    if (state.active) return;
    if (state.permissionDenied) return;

    state.active = true;
    state.restartCount = 0;
    state.noSpeechStreak = 0;

    const recognition = new SpeechRecognition();
    recognition.lang = CONFIG.lang;
    recognition.continuous = CONFIG.continuous;
    recognition.interimResults = CONFIG.interimResults;
    recognition.maxAlternatives = CONFIG.maxAlternatives;
    state.recognition = recognition;

    recognition.onresult = (event) => {
      state.restartCount = 0;
      state.noSpeechStreak = 0;

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = (result?.[0]?.transcript || "").trim();
        if (!result.isFinal || !text) continue;

        state.transcript.push({ time: nowStamp(), text });

        post("transcript_line", {
          mediaId: state.id,
          title: mediaTitle(media),
          time: state.transcript[state.transcript.length - 1].time,
          text,
          lineCount: state.transcript.length,
          inputMode: state.inputMode,
          url: location.href,
        });
      }
    };

    recognition.onerror = (event) => {
      const err = event?.error || "unknown";

      if (err === "aborted") return;

      if (err === "no-speech") {
        state.noSpeechStreak += 1;
        if (state.noSpeechStreak % CONFIG.noSpeechWarnEvery === 0) {
          warn(`no-speech x${state.noSpeechStreak} (${state.inputMode})`);
          post("transcript_error", {
            mediaId: state.id,
            error: "no_speech",
            message: `No speech detected yet (${state.inputMode}).`,
            inputMode: state.inputMode,
          });
        }
        return;
      }

      if (err === "not-allowed" || err === "service-not-allowed") {
        state.permissionDenied = true;
        state.active = false;
        stopPeriodicEmitter(state);
        post("transcript_error", {
          mediaId: state.id,
          error: err,
          message: "Microphone permission denied. Allow mic and reload page.",
        });
        return;
      }

      if (err === "network") {
        warn("Speech service network issue; will retry on onend.");
        return;
      }

      post("transcript_error", {
        mediaId: state.id,
        error: err,
        message: `SpeechRecognition error: ${err}`,
      });
    };

    recognition.onend = () => {
      if (!state.active) return;
      if (media.paused || media.ended) return;
      if (state.permissionDenied) return;

      state.restartCount += 1;
      if (state.restartCount > CONFIG.maxConsecutiveRestarts) {
        state.active = false;
        stopPeriodicEmitter(state);
        post("transcript_error", {
          mediaId: state.id,
          error: "max_restarts",
          message: "Stopped after too many recognition restarts.",
        });
        return;
      }

      setTimeout(() => {
        if (!state.active || state.permissionDenied || media.paused || media.ended) return;
        try {
          startEngine(recognition, media, state);
        } catch (err) {
          warn("restart failed:", err?.message || err);
        }
      }, CONFIG.restartDelayMs);
    };

    try {
      startEngine(recognition, media, state);
      startPeriodicEmitter(media, state);

      post("transcript_started", {
        mediaId: state.id,
        title: mediaTitle(media),
        inputMode: state.inputMode,
        reason,
        url: location.href,
      });

      log(`STARTED (${state.inputMode}) for "${mediaTitle(media)}"`);
    } catch (err) {
      state.active = false;
      post("transcript_error", {
        mediaId: state.id,
        error: "start_failed",
        message: err?.message || String(err),
      });
    }
  }

  function pauseRecognition(media) {
    const state = states.get(media);
    if (!state) return;

    state.active = false;
    stopPeriodicEmitter(state);
    try { state.recognition?.stop(); } catch {}

    post("transcript_paused", {
      mediaId: state.id,
      title: mediaTitle(media),
      transcript: [...state.transcript],
      lineCount: state.transcript.length,
      inputMode: state.inputMode,
      url: location.href,
    });
  }

  function completeRecognition(media, reason = "ended") {
    const state = states.get(media);
    if (!state) return;

    state.active = false;
    stopPeriodicEmitter(state);
    try { state.recognition?.stop(); } catch {}

    post("transcript_complete", {
      mediaId: state.id,
      title: mediaTitle(media),
      transcript: [...state.transcript],
      lineCount: state.transcript.length,
      saveCount: state.saveCount,
      inputMode: state.inputMode,
      reason,
      url: location.href,
    });

    state.transcript = [];
    state.lastEmittedIndex = 0;
    state.saveCount = 0;
    state.startedAt = Date.now();
    state.restartCount = 0;
    state.noSpeechStreak = 0;
  }

  function attachMedia(media) {
    const state = getState(media);
    if (state.attached) return;
    state.attached = true;

    media.addEventListener("play", () => startRecognition(media, "play"));
    media.addEventListener("playing", () => {
      const s = getState(media);
      if (!s.active) startRecognition(media, "playing");
    });
    media.addEventListener("pause", () => pauseRecognition(media));
    media.addEventListener("ended", () => completeRecognition(media, "ended"));

    if (!media.paused && !media.ended && media.readyState > 2) {
      startRecognition(media, "already_playing");
    }

    log(`armed <${media.tagName.toLowerCase()}>: "${mediaTitle(media)}"`);
  }

  function attachExistingMedia() {
    document.querySelectorAll("video, audio").forEach((m) => attachMedia(m));
  }

  function installMediaObserver() {
    const obs = new MutationObserver((mutations) => {
      for (const mut of mutations) {
        for (const node of mut.addedNodes) {
          if (node.nodeType !== Node.ELEMENT_NODE) continue;
          if (node.tagName === "VIDEO" || node.tagName === "AUDIO") {
            attachMedia(node);
          }
          node.querySelectorAll?.("video, audio").forEach((m) => attachMedia(m));
        }
      }
    });

    obs.observe(document.documentElement, { childList: true, subtree: true });
  }

  function flushAll(reason) {
    document.querySelectorAll("video, audio").forEach((media) => {
      const state = states.get(media);
      if (!state) return;

      state.active = false;
      stopPeriodicEmitter(state);
      try { state.recognition?.stop(); } catch {}

      if (state.transcript.length > 0) {
        post("transcript_complete", {
          mediaId: state.id,
          title: mediaTitle(media),
          transcript: [...state.transcript],
          lineCount: state.transcript.length,
          saveCount: state.saveCount,
          inputMode: state.inputMode,
          reason,
          url: location.href,
        });

        state.transcript = [];
        state.lastEmittedIndex = 0;
        state.saveCount = 0;
      }
    });
  }

  function ensureAnyPlayingStarted(reason) {
    const playing = [...document.querySelectorAll("video, audio")]
      .find((m) => !m.paused && !m.ended && m.readyState > 2);
    if (!playing) return;

    const state = getState(playing);
    if (!state.active) startRecognition(playing, reason);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (event.data?.source !== "transcriber_content_script") return;

    if (event.data.type === "force_start") {
      ensureAnyPlayingStarted("force_start");
      return;
    }

    if (event.data.type === "force_download") {
      flushAll("force_download");
    }
  });

  window.addEventListener("beforeunload", () => flushAll("beforeunload"));
  window.addEventListener("pagehide", () => flushAll("pagehide"));

  attachExistingMedia();
  installMediaObserver();

  setInterval(() => ensureAnyPlayingStarted("poll"), CONFIG.autoplayPollMs);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      ensureAnyPlayingStarted("visible");
    }
  });

  if (IS_YOUTUBE) {
    setInterval(() => {
      if (location.href !== lastKnownUrl) {
        lastKnownUrl = location.href;
        attachExistingMedia();
        ensureAnyPlayingStarted("youtube_route_change");
      }
    }, CONFIG.youtubeUrlCheckMs);
  }

  log("✅ main-world transcriber loaded");
})();
