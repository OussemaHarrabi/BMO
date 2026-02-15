// =============================================================================
// content.js — Content Script (injected into every page)
// =============================================================================
// Architecture:
//   • TRIGGERS config object at the top for easy enable/disable.
//   • Global 3-second cooldown across ALL triggers.
//   • passive: true on every high-frequency listener (scroll, mousemove).
//   • Each trigger sends { type: "capture_request", triggerType } to background.js.
//
// Trigger Categories:
//   A. High Intent & Extraction  — selection, copy/cut, context menu, find
//   B. Reading & Deep Engagement — scroll-stop, zoom, idle dwell
//   C. Workflow & Comparison     — tab return, app switch
//   D. Frustration Signals       — rage click, erratic scroll
//   E. Social Media Engagement   — Facebook like/reaction, Instagram like
// =============================================================================

(() => {
  "use strict";

  // ╔═══════════════════════════════════════════════════════════════════════════╗
  // ║  ORPHAN GUARD                                                            ║
  // ║  When the extension is reloaded during development, old content scripts  ║
  // ║  become "orphaned" — chrome.runtime is disconnected and every API call   ║
  // ║  throws "Extension context invalidated".  We detect this early and       ║
  // ║  disable everything to avoid console spam and wasted CPU.                ║
  // ╚═══════════════════════════════════════════════════════════════════════════╝

  // Collect all timers/intervals so we can tear them down on orphan detection
  const _timers    = [];   // setTimeout ids
  const _intervals = [];   // setInterval ids

  function isExtensionAlive() {
    try {
      return !!chrome.runtime?.id;
    } catch {
      return false;
    }
  }

  // Periodic orphan check — if the context dies, clean up everything
  const orphanCheckId = setInterval(() => {
    if (!isExtensionAlive()) {
      console.warn("[Capture] Extension context invalidated — tearing down content script.");
      clearInterval(orphanCheckId);
      _timers.forEach(clearTimeout);
      _intervals.forEach(clearInterval);
      // Remove all event listeners by letting the IIFE scope be GC'd
      // (listeners use named refs so they'll be collected)
    }
  }, 2000);
  _intervals.push(orphanCheckId);

  // ╔═══════════════════════════════════════════════════════════════════════════╗
  // ║  TRIGGER CONFIGURATION                                                   ║
  // ║  Set  enabled: false  to disable any trigger without removing code.      ║
  // ╚═══════════════════════════════════════════════════════════════════════════╝

  const TRIGGERS = {
    // ── A. High Intent & Extraction ──────────────────────────────────────────
    selectionInterest: {
      enabled: true,
      label: "selection_interest",
      charThreshold: 50,       // minimum characters selected
      debounceMs: 1000,        // wait for selection to stabilize
    },
    copyCutAction: {
      enabled: true,
      label: "copy_cut_action",
    },
    contextMenu: {
      enabled: true,
      label: "context_menu",
    },
    searchFound: {
      enabled: true,
      label: "search_found",
      scrollThresholdPx: 100,  // scroll distance after Ctrl+F to count as "found"
      windowMs: 2000,          // time window after Ctrl+F to watch for scroll
    },

    // ── B. Reading & Deep Engagement ─────────────────────────────────────────
    scrollStopRead: {
      enabled: true,
      label: "scroll_stop_read",
      minVelocity: 0.3,       // px/ms — must have been scrolling at least this fast
      stillMs: 3000,           // how long the user must stay still after stopping
    },
    zoomDetail: {
      enabled: true,
      label: "zoom_detail",
    },
    deepReadDwell: {
      enabled: true,
      label: "deep_read_dwell",
      idleMs: 10000,           // no mouse / keyboard / scroll for this long
    },

    // ── C. Workflow & Comparison ─────────────────────────────────────────────
    tabReturn: {
      enabled: true,
      label: "tab_return",
      delayMs: 500,            // capture 500 ms after tab becomes visible again
    },
    appSwitch: {
      enabled: true,
      label: "app_switch",
    },

    // ── E. Social Media Engagement ──────────────────────────────────────────
    facebookLike: {
      enabled: true,
      label: "facebook_like",
      confirmMs: 600,            // wait for DOM to confirm the like state change
    },
    instagramLike: {
      enabled: true,
      label: "instagram_like",
      confirmMs: 600,            // wait for DOM to confirm the like state change
    },

    // ── D. Frustration Signals ───────────────────────────────────────────────
    rageClick: {
      enabled: true,
      label: "rage_click",
      clickCount: 3,           // clicks on the same element
      windowMs: 1000,          // within this time window
    },
    scanSearch: {
      enabled: true,
      label: "scan_search",
      directionChanges: 2,     // up→down→up = 2 reversals
      windowMs: 2000,          // within this time window
    },
  };

  // ╔═══════════════════════════════════════════════════════════════════════════╗
  // ║  GLOBAL COOLDOWN SYSTEM                                                  ║
  // ║  Once ANY capture fires, suppress all triggers for COOLDOWN_MS.          ║
  // ╚═══════════════════════════════════════════════════════════════════════════╝

  const COOLDOWN_MS = 3000;
  let lastCaptureRequestTime = 0;

  // ╔═══════════════════════════════════════════════════════════════════════════╗
  // ║  VIDEO PLAYBACK DETECTION                                                ║
  // ║  Suppresses ALL captures while a video is actively playing on the page.  ║
  // ║  Detects <video> elements, YouTube embeds, and common video players.     ║
  // ║  Once the video is paused/ended, captures resume normally.               ║
  // ╚═══════════════════════════════════════════════════════════════════════════╝

  let _videoPlaying = false;

  /**
   * Check if any video on the page is currently playing.
   * Handles:
   *   • Native <video> elements (HTML5 players, Netflix, Disney+, etc.)
   *   • YouTube embeds (checks for playing state classes)
   *   • Fullscreen video heuristic
   */
  function isVideoPlaying() {
    // 1. Check all <video> elements on the page
    const videos = document.querySelectorAll("video");
    for (const video of videos) {
      if (!video.paused && !video.ended && video.readyState > 2 && video.currentTime > 0) {
        // Ignore tiny preview/thumbnail videos (< 200×150)
        // to avoid suppressing captures on pages with autoplay thumbnails
        if (video.videoWidth >= 200 && video.videoHeight >= 150) {
          return true;
        }
        // Also consider videos that are visually large on screen
        const rect = video.getBoundingClientRect();
        if (rect.width >= 200 && rect.height >= 150) {
          return true;
        }
      }
    }

    // 2. Fullscreen API — if the page is in fullscreen and has a video, very
    //    likely the user is watching something
    if (document.fullscreenElement) {
      const fsVideos = document.fullscreenElement.querySelectorAll?.("video") || [];
      for (const video of fsVideos) {
        if (!video.paused && !video.ended) return true;
      }
    }

    return false;
  }

  // ── Attach play/pause listeners to all <video> elements ──────────────────
  // We use a MutationObserver to catch dynamically added video elements
  // (SPAs, lazy-loaded players, etc.)

  function attachVideoListeners(video) {
    if (video._captureListenersAttached) return;
    video._captureListenersAttached = true;

    video.addEventListener("play",    () => { _videoPlaying = true;  console.log("[Capture] ▶️  Video playing — captures paused."); });
    video.addEventListener("playing", () => { _videoPlaying = true; });
    video.addEventListener("pause",   () => { _videoPlaying = isVideoPlaying(); if (!_videoPlaying) console.log("[Capture] ⏸️  Video paused — captures resumed."); });
    video.addEventListener("ended",   () => { _videoPlaying = isVideoPlaying(); if (!_videoPlaying) console.log("[Capture] ⏹️  Video ended — captures resumed."); });
    video.addEventListener("emptied", () => { _videoPlaying = isVideoPlaying(); });
  }

  // Attach to any existing videos
  document.querySelectorAll("video").forEach(attachVideoListeners);

  // Watch for dynamically added videos
  const videoObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (node.tagName === "VIDEO") {
          attachVideoListeners(node);
        }
        // Also check inside added subtrees (e.g. a <div> containing a <video>)
        const innerVideos = node.querySelectorAll?.("video") || [];
        innerVideos.forEach(attachVideoListeners);
      }
    }
  });
  videoObserver.observe(document.documentElement, { childList: true, subtree: true });

  // Periodic fallback check (handles edge cases like picture-in-picture,
  // shadow DOM players, and iframes that inject video elements)
  const videoCheckId = setInterval(() => {
    const nowPlaying = isVideoPlaying();
    if (nowPlaying !== _videoPlaying) {
      _videoPlaying = nowPlaying;
      console.log(`[Capture] ${nowPlaying ? "▶️  Video detected playing — captures paused." : "⏹️  Video stopped — captures resumed."}`);
    }
  }, 2000);
  _intervals.push(videoCheckId);

  /**
   * Send a capture request to the background service worker.
   * Automatically enforced by the global cooldown — if the last capture was
   * less than COOLDOWN_MS ago, the request is silently dropped.
   * Also suppressed while a video is actively playing on the page.
   */
  function requestCapture(triggerLabel) {
    // Bail out immediately if the extension context has been invalidated
    if (!isExtensionAlive()) return;

    // ── Video playback guard ──
    // Re-check live state (the cached flag + a fresh DOM check)
    if (_videoPlaying || isVideoPlaying()) {
      _videoPlaying = true;
      console.log(
        `[Capture] 🎬 Video playing — suppressed "${triggerLabel}"`
      );
      return;
    }

    const now = Date.now();
    if (now - lastCaptureRequestTime < COOLDOWN_MS) {
      console.log(
        `[Capture] ⏳ Cooldown — suppressed "${triggerLabel}" ` +
        `(${COOLDOWN_MS - (now - lastCaptureRequestTime)} ms left)`
      );
      return;
    }
    lastCaptureRequestTime = now;
    console.log(`[Capture] 🔥 Trigger fired → "${triggerLabel}"`);

    try {
      chrome.runtime.sendMessage(
        { type: "capture_request", triggerType: triggerLabel },
        (response) => {
          if (chrome.runtime.lastError) {
            console.warn("[Capture] sendMessage error:", chrome.runtime.lastError.message);
          }
        }
      );
    } catch (err) {
      // Extension context invalidated — stop future calls
      console.warn("[Capture] Extension context lost:", err.message);
    }
  }

  // ╔═══════════════════════════════════════════════════════════════════════════╗
  // ║  SHARED STATE: Activity tracker (used by multiple triggers)              ║
  // ╚═══════════════════════════════════════════════════════════════════════════╝

  // Updated by mouse, keyboard, and scroll listeners.
  // Used by: deepReadDwell
  let lastActivityTime = Date.now();

  function markActivity() {
    lastActivityTime = Date.now();
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  A-1 │ LARGE TEXT SELECTION  (> N characters, debounced)
  // ══════════════════════════════════════════════════════════════════════════════
  //  Listens to "selectionchange" on the document. After the selection stops
  //  changing for `debounceMs`, we check if the selected text exceeds the
  //  character threshold. This avoids capturing while the user is still dragging.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.selectionInterest.enabled) {
    const cfg = TRIGGERS.selectionInterest;
    let selectionDebounce = null;

    document.addEventListener("selectionchange", () => {
      clearTimeout(selectionDebounce);
      selectionDebounce = setTimeout(() => {
        const text = window.getSelection()?.toString() || "";
        if (text.length > cfg.charThreshold) {
          requestCapture(cfg.label);
        }
      }, cfg.debounceMs);
    });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  A-2 │ COPY / CUT COMMAND
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.copyCutAction.enabled) {
    const cfg = TRIGGERS.copyCutAction;

    document.addEventListener("copy", () => requestCapture(cfg.label));
    document.addEventListener("cut",  () => requestCapture(cfg.label));
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  A-3 │ CONTEXT MENU (Right-click — mousedown button 2)
  // ══════════════════════════════════════════════════════════════════════════════
  //  We capture on mousedown (button === 2) rather than the "contextmenu" event
  //  so the screenshot fires BEFORE the context menu renders over the page.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.contextMenu.enabled) {
    const cfg = TRIGGERS.contextMenu;

    document.addEventListener("mousedown", (e) => {
      if (e.button === 2) {             // 2 = secondary / right-click
        requestCapture(cfg.label);
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  A-4 │ "FIND ON PAGE" SUCCESS  (Ctrl+F → scroll > 100 px within 2 s)
  // ══════════════════════════════════════════════════════════════════════════════
  //  Heuristic: the user presses Ctrl+F / Cmd+F to open the browser's find bar.
  //  If the page then scrolls more than scrollThresholdPx within windowMs, it
  //  very likely means the browser jumped to a match — the user "found" something.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.searchFound.enabled) {
    const cfg = TRIGGERS.searchFound;
    let findActive = false;
    let findScrollY = 0;
    let findTimer = null;

    document.addEventListener("keydown", (e) => {
      // Ctrl+F (Windows/Linux) or Cmd+F (Mac)
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        findActive = true;
        findScrollY = window.scrollY;
        clearTimeout(findTimer);

        // After the time window expires, stop monitoring
        findTimer = setTimeout(() => {
          findActive = false;
        }, cfg.windowMs);
      }
    });

    window.addEventListener("scroll", () => {
      if (!findActive) return;
      const delta = Math.abs(window.scrollY - findScrollY);
      if (delta > cfg.scrollThresholdPx) {
        findActive = false;
        clearTimeout(findTimer);
        requestCapture(cfg.label);
      }
    }, { passive: true });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  B-1 │ SCROLL HOOK — STOP  (fast scroll → sudden stop for 3 s)
  // ══════════════════════════════════════════════════════════════════════════════
  //
  //  ── Scroll Velocity Calculation ──
  //
  //  On each scroll event we sample two values:
  //     scrollY_now   = window.scrollY          (pixels from top)
  //     time_now      = Date.now()              (milliseconds)
  //
  //  And compute:
  //     velocity = |scrollY_now − scrollY_prev| / (time_now − time_prev)
  //
  //  Units: px/ms.  A velocity of 0.3 px/ms = 300 px/s.
  //
  //  We track the *peak* velocity during a scroll burst. When the scroll events
  //  stop (no new scroll for `stillMs`), we check whether the peak velocity
  //  exceeded `minVelocity`. If so, the user was actively scrolling and then
  //  suddenly stopped — they found something interesting.
  //
  //  The timer resets on every scroll event so it only fires when scrolling
  //  truly stops.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.scrollStopRead.enabled) {
    const cfg = TRIGGERS.scrollStopRead;

    let prevScrollY = window.scrollY;
    let prevScrollTime = Date.now();
    let recentMaxVelocity = 0;       // peak velocity in the current scroll burst
    let scrollStopTimer = null;

    window.addEventListener("scroll", () => {
      const now = Date.now();
      const currentY = window.scrollY;
      const dt = now - prevScrollTime;

      if (dt > 0) {
        // ── velocity (px/ms) = absolute pixel distance / elapsed time ──
        const velocity = Math.abs(currentY - prevScrollY) / dt;
        if (velocity > recentMaxVelocity) {
          recentMaxVelocity = velocity;
        }
      }

      prevScrollY = currentY;
      prevScrollTime = now;

      // Reset the "stopped scrolling" countdown on every scroll event
      clearTimeout(scrollStopTimer);
      scrollStopTimer = setTimeout(() => {
        // Timer expired → user stopped scrolling
        if (recentMaxVelocity >= cfg.minVelocity) {
          requestCapture(cfg.label);
        }
        // Reset velocity tracker for the next burst
        recentMaxVelocity = 0;
      }, cfg.stillMs);
    }, { passive: true });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  B-2 │ ZOOM IN  (devicePixelRatio increases)
  // ══════════════════════════════════════════════════════════════════════════════
  //  We use matchMedia to watch for changes in the device's pixel ratio without
  //  polling. When the DPR *increases* the user has zoomed in (Ctrl++ or
  //  pinch-to-zoom). We re-register the watcher each time because the media
  //  query value changes.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.zoomDetail.enabled) {
    const cfg = TRIGGERS.zoomDetail;
    let lastDPR = window.devicePixelRatio;

    function watchDPR() {
      const mql = window.matchMedia(
        `(resolution: ${window.devicePixelRatio}dppx)`
      );

      mql.addEventListener("change", () => {
        const newDPR = window.devicePixelRatio;
        if (newDPR > lastDPR) {
          // User zoomed IN — capture
          requestCapture(cfg.label);
        }
        lastDPR = newDPR;
        // Re-attach with the new DPR value
        watchDPR();
      }, { once: true });
    }

    watchDPR();
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  B-3 │ LONG DWELL / IDLE  (no interaction for 10 seconds)
  // ══════════════════════════════════════════════════════════════════════════════
  //  We track the last time ANY interaction occurred (mouse, keyboard, scroll,
  //  touch). A setInterval checks every second whether `idleMs` has elapsed.
  //  Once triggered, it won't fire again until the user interacts and then goes
  //  idle again.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.deepReadDwell.enabled) {
    const cfg = TRIGGERS.deepReadDwell;
    let dwellFired = false;            // prevent repeated fires while idle

    // Mark activity from all interaction types (passive where possible)
    window.addEventListener("scroll",     markActivity, { passive: true });
    window.addEventListener("mousemove",  markActivity, { passive: true });
    window.addEventListener("keydown",    markActivity);
    window.addEventListener("mousedown",  markActivity);
    window.addEventListener("touchstart", markActivity, { passive: true });

    const dwellIntervalId = setInterval(() => {
      const idleDuration = Date.now() - lastActivityTime;
      if (idleDuration >= cfg.idleMs && !dwellFired) {
        dwellFired = true;
        requestCapture(cfg.label);
      }
      // Reset the flag once the user interacts again
      if (idleDuration < cfg.idleMs) {
        dwellFired = false;
      }
    }, 1000);
    _intervals.push(dwellIntervalId);
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  C-1 │ TAB RETURN  (visibilityState → "visible", capture after delay)
  // ══════════════════════════════════════════════════════════════════════════════
  //  The user switched to another tab and just came back. We wait `delayMs`
  //  to make sure the tab is fully painted, then capture — but only if the tab
  //  is still visible (they didn't instantly switch away again).
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.tabReturn.enabled) {
    const cfg = TRIGGERS.tabReturn;

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        setTimeout(() => {
          // Only fire if the tab is *still* visible after the delay
          if (document.visibilityState === "visible") {
            requestCapture(cfg.label);
          }
        }, cfg.delayMs);
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  C-2 │ APP SWITCH / BLUR  (user Alt-Tabs or clicks away from browser)
  // ══════════════════════════════════════════════════════════════════════════════
  //  Captures the page state at the moment the user leaves — useful for seeing
  //  what they were looking at before switching to their notes app or IDE.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.appSwitch.enabled) {
    const cfg = TRIGGERS.appSwitch;

    window.addEventListener("blur", () => {
      requestCapture(cfg.label);
    });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  D-1 │ RAGE CLICK  (same element clicked N times within a time window)
  // ══════════════════════════════════════════════════════════════════════════════
  //  We maintain a small ring-buffer of recent clicks. Each click is stored
  //  with its target and timestamp. After pruning old entries, we count how
  //  many of the remaining clicks hit the same DOM element. If that count
  //  reaches `clickCount`, the user is frustrated.
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.rageClick.enabled) {
    const cfg = TRIGGERS.rageClick;

    let clickHistory = [];             // array of { target, time }

    document.addEventListener("click", (e) => {
      const now = Date.now();
      // Push this click onto the history
      clickHistory.push({ target: e.target, time: now });

      // Prune clicks older than the window
      clickHistory = clickHistory.filter(
        (c) => now - c.time <= cfg.windowMs
      );

      // Count how many recent clicks hit the same element
      const sameTargetClicks = clickHistory.filter(
        (c) => c.target === e.target
      ).length;

      if (sameTargetClicks >= cfg.clickCount) {
        requestCapture(cfg.label);
        clickHistory = [];             // reset after firing
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  D-2 │ ERRATIC SCROLL / SCANNING  (rapid direction reversals)
  // ══════════════════════════════════════════════════════════════════════════════
  //
  //  ── Direction Reversal Detection ──
  //
  //  On each scroll event we compare scrollY to the previous value:
  //      direction = (scrollY > prevScrollY) ? "down" : "up"
  //
  //  Every time the direction differs from the previous direction we record a
  //  "reversal" with a timestamp.  If we accumulate ≥ `directionChanges`
  //  reversals within `windowMs`, the user is frantically scanning the page.
  //
  //  Example for directionChanges = 2:
  //      ↓ scroll down  →  ↑ scroll up (reversal 1)  →  ↓ scroll down (reversal 2)  → FIRE
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.scanSearch.enabled) {
    const cfg = TRIGGERS.scanSearch;

    let erraticPrevY = window.scrollY;
    let erraticPrevDirection = null;   // "up" | "down" | null
    let reversals = [];                // array of timestamps

    window.addEventListener("scroll", () => {
      const currentY = window.scrollY;
      const now = Date.now();

      // Determine current scroll direction
      if (currentY === erraticPrevY) return;    // no net movement
      const direction = currentY > erraticPrevY ? "down" : "up";

      // Check for a direction reversal
      if (erraticPrevDirection !== null && direction !== erraticPrevDirection) {
        reversals.push(now);

        // Prune reversals outside the time window
        reversals = reversals.filter((t) => now - t <= cfg.windowMs);

        if (reversals.length >= cfg.directionChanges) {
          requestCapture(cfg.label);
          reversals = [];              // reset after firing
        }
      }

      erraticPrevY = currentY;
      erraticPrevDirection = direction;
    }, { passive: true });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  E-1 │ FACEBOOK LIKE / REACTION DETECTION
  // ══════════════════════════════════════════════════════════════════════════════
  //
  //  Detects when the user likes or reacts to a Facebook post.
  //
  //  Strategy: Click interception on Like/Reaction buttons (matched via
  //  aria-label) followed by a short confirmation delay. We capture on the
  //  click itself because the interesting content is the post, and we want
  //  the screenshot before any overlay/popover changes the view.
  //
  //  Matched actions:
  //    • Clicking the "Like" button (aria-label="Like", role="button")
  //    • Selecting a reaction from the popover (Love, Haha, Wow, Sad, Angry)
  //
  //  We intentionally do NOT fire when the user UN-likes a post
  //  (aria-label="Remove Like" etc.) — only new engagement is interesting.
  //
  //  Both click listener and MutationObserver are used for robustness:
  //    • Click listener catches direct button clicks
  //    • MutationObserver catches double-tap and programmatic likes
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.facebookLike.enabled) {
    const cfg = TRIGGERS.facebookLike;
    const isFacebook = /^https?:\/\/(www\.)?facebook\.com/i.test(location.href);

    if (isFacebook) {
      // ── Facebook Reaction button labels (aria-label based for stability) ──
      const FB_REACTION_LABELS = ["Love", "Haha", "Wow", "Sad", "Angry", "Care"];

      // ── Click listener (capturing phase to fire before React handlers) ──
      document.addEventListener("click", (e) => {
        const target = e.target;

        // 1. Direct "Like" button click
        const likeBtn = target.closest?.('[aria-label="Like"][role="button"]');
        if (likeBtn) {
          // Small delay so the screenshot captures the post content,
          // not a transitional state
          setTimeout(() => requestCapture(cfg.label), cfg.confirmMs);
          return;
        }

        // 2. Reaction selection from the hover popover
        //    Reactions render in a portal/dialog, so we match by aria-label
        for (const reaction of FB_REACTION_LABELS) {
          const reactionBtn = target.closest?.(`[aria-label="${reaction}"][role="button"]`);
          if (reactionBtn) {
            setTimeout(() => requestCapture(cfg.label), cfg.confirmMs);
            return;
          }
        }
      }, true);  // capturing phase

      // ── MutationObserver for state-change confirmation ──
      // Watches for aria-label changes on buttons inside the feed.
      // This catches edge cases like keyboard-driven likes.
      const feedEl = document.querySelector('[role="feed"]');
      if (feedEl) {
        const fbObserver = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            if (mutation.type !== "attributes") continue;
            if (mutation.attributeName !== "aria-label") continue;

            const el = mutation.target;
            const newLabel = el.getAttribute("aria-label");
            const oldLabel = mutation.oldValue;

            // Detect transition: "Like" → "Remove Like" (or "Remove Love", etc.)
            if (oldLabel === "Like" && newLabel && newLabel.startsWith("Remove ")) {
              setTimeout(() => requestCapture(cfg.label), cfg.confirmMs);
            }
          }
        });

        fbObserver.observe(feedEl, {
          attributes: true,
          attributeFilter: ["aria-label"],
          attributeOldValue: true,
          subtree: true,
        });
      }

      console.log("[Capture] Facebook like detection armed.");
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  //  E-2 │ INSTAGRAM LIKE / HEART DETECTION
  // ══════════════════════════════════════════════════════════════════════════════
  //
  //  Detects when the user likes an Instagram post via:
  //    • Clicking the heart icon (svg[aria-label="Like"])
  //    • Double-tapping a post image (detected via state change, not gesture)
  //
  //  Instagram replaces the entire <svg> element on state change (unlike
  //  Facebook which mutates attributes). We handle both approaches:
  //    1. Click listener on the heart button
  //    2. MutationObserver watching for SVG swaps (Like → Unlike)
  //
  //  We only fire on LIKE actions, not un-likes.
  //
  //  Selectors rely on aria-label for stability:
  //    • svg[aria-label="Like"]     — not yet liked
  //    • svg[aria-label="Unlike"]   — already liked
  //    • fill="#ed4956"             — Instagram red (liked state)
  // ══════════════════════════════════════════════════════════════════════════════
  if (TRIGGERS.instagramLike.enabled) {
    const cfg = TRIGGERS.instagramLike;
    const isInstagram = /^https?:\/\/(www\.)?instagram\.com/i.test(location.href);

    if (isInstagram) {
      // ── Click listener ──
      document.addEventListener("click", (e) => {
        const target = e.target;

        // Match clicks on the Like SVG or any element inside it
        const likeSvg = target.closest?.('svg[aria-label="Like"]');
        if (likeSvg) {
          // Mark this SVG's parent article as having a pending like
          const article = likeSvg.closest("article");
          // Capture after a short delay to let the UI update
          setTimeout(() => {
            requestCapture(cfg.label);
          }, cfg.confirmMs);
          return;
        }

        // Also catch clicks on the button wrapping the SVG
        const likeBtn = target.closest?.('button');
        if (likeBtn) {
          const svg = likeBtn.querySelector('svg[aria-label="Like"]');
          if (svg) {
            const article = likeBtn.closest("article");
            setTimeout(() => {
              requestCapture(cfg.label);
            }, cfg.confirmMs);
          }
        }
      }, true);  // capturing phase

      // ── MutationObserver for double-tap likes ──
      // When the user double-taps a photo, Instagram changes the heart SVG
      // from aria-label="Like" to aria-label="Unlike" without a click on the
      // heart button itself. We detect this via childList mutations (Instagram
      // replaces the entire SVG node) and attribute mutations.
      const mainEl = document.querySelector("main") || document.body;

      const igObserver = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          // ── Strategy A: Attribute change (aria-label or fill) ──
          if (mutation.type === "attributes") {
            const el = mutation.target;
            if (el.tagName === "svg" || el.tagName === "SVG") {
              const newLabel = el.getAttribute("aria-label");
              if (newLabel === "Unlike") {
                // Confirm this is a new like, not a page load rendering
                const article = el.closest("article");
                // Use a data attribute to avoid re-firing on the same element
                if (article && !article.dataset._captureLikeFired) {
                  article.dataset._captureLikeFired = "1";
                  setTimeout(() => {
                    requestCapture(cfg.label);
                    // Allow re-detection after 5 seconds (user could unlike
                    // and re-like)
                    setTimeout(() => {
                      delete article.dataset._captureLikeFired;
                    }, 5000);
                  }, cfg.confirmMs);
                }
              }
            }
          }

          // ── Strategy B: Node replacement (Instagram swaps SVG nodes) ──
          if (mutation.type === "childList") {
            for (const node of mutation.addedNodes) {
              if (node.nodeType !== Node.ELEMENT_NODE) continue;

              // Check the added node itself
              let unlikeSvg = null;
              if ((node.tagName === "svg" || node.tagName === "SVG") &&
                  node.getAttribute("aria-label") === "Unlike") {
                unlikeSvg = node;
              } else {
                unlikeSvg = node.querySelector?.('svg[aria-label="Unlike"]');
              }

              if (unlikeSvg) {
                const article = unlikeSvg.closest("article");
                if (article && !article.dataset._captureLikeFired) {
                  article.dataset._captureLikeFired = "1";
                  setTimeout(() => {
                    requestCapture(cfg.label);
                    setTimeout(() => {
                      delete article.dataset._captureLikeFired;
                    }, 5000);
                  }, cfg.confirmMs);
                }
              }
            }
          }
        }
      });

      igObserver.observe(mainEl, {
        attributes: true,
        attributeFilter: ["aria-label", "fill"],
        childList: true,
        subtree: true,
      });

      // ── Handle SPA navigation ──
      // Instagram is an SPA — navigating between feed/explore/profile doesn't
      // reload the page. We watch for URL changes and re-attach the observer
      // if the main element gets replaced.
      let lastIgUrl = location.href;
      const igNavObserver = new MutationObserver(() => {
        if (location.href !== lastIgUrl) {
          lastIgUrl = location.href;
          // Re-attach observer to new main element if it changed
          const newMain = document.querySelector("main");
          if (newMain && newMain !== mainEl) {
            igObserver.disconnect();
            igObserver.observe(newMain, {
              attributes: true,
              attributeFilter: ["aria-label", "fill"],
              childList: true,
              subtree: true,
            });
          }
        }
      });
      igNavObserver.observe(document.body, { childList: true, subtree: true });

      console.log("[Capture] Instagram like detection armed.");
    }
  }

  // ── Boot message ───────────────────────────────────────────────────────────
  const enabledCount = Object.values(TRIGGERS).filter((t) => t.enabled).length;
  console.log(
    `[Capture Extension] Content script loaded — ${enabledCount}/${Object.keys(TRIGGERS).length} triggers armed.`
  );
})();
