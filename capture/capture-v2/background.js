// =============================================================================
// background.js — Service Worker  (Manifest V3)
// =============================================================================
// Responsibilities:
//   1. Listen for "capture_request" messages from content.js.
//   2. Verify the requesting tab is the active tab in its window (so we don't
//      screenshot the wrong tab).
//   3. Use chrome.tabs.captureVisibleTab() to grab a PNG screenshot.
//   4. Use chrome.downloads.download() to save the file.
//   5. Enforce a server-side 3 s cooldown (belt-and-suspenders with content.js).
//
// Key Fix (vs. previous version):
//   - manifest.json now has  host_permissions: ["<all_urls>"]  which is
//     REQUIRED for captureVisibleTab to work on programmatic triggers.
//     The  activeTab  permission alone only works after a user gesture
//     (clicking the extension icon / keyboard shortcut).
// =============================================================================

// ── Suppress Chrome's download UI (bubble / shelf) ──────────────────────────
// This makes every chrome.downloads.download() call completely silent —
// no popup, no download bar, no permission prompt.  Requires "downloads.ui".
try {
  chrome.downloads.setUiOptions({ enabled: false });
  console.log("[Capture BG] Download UI suppressed — downloads will be silent.");
} catch (e) {
  console.warn("[Capture BG] Could not suppress download UI:", e.message);
}

// ── Cooldown ─────────────────────────────────────────────────────────────────
const GLOBAL_COOLDOWN_MS = 3000;
let lastCaptureTime = 0;

// ── Capture Statistics (for debugging in the SW console) ─────────────────────
const captureStats = {};

// ── Restricted URL patterns that captureVisibleTab cannot handle ─────────────
const RESTRICTED_URL_PATTERNS = [
  /^chrome:\/\//,
  /^chrome-extension:\/\//,
  /^devtools:\/\//,
  /^edge:\/\//,
  /^about:/,
  /^chrome-search:\/\//,
  /^https:\/\/chrome\.google\.com\/webstore/,
  /^https:\/\/chromewebstore\.google\.com/,
];

function isRestrictedUrl(url) {
  return RESTRICTED_URL_PATTERNS.some((pattern) => pattern.test(url || ""));
}

// ── Message Handler ──────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  // ── Handle transcript save requests ──────────────────────────────────────
  if (message.type === "save_transcript") {
    (async () => {
      try {
        const { text, filename } = message;
        if (!text || !filename) {
          console.warn("[Capture BG] save_transcript missing text or filename.");
          sendResponse({ success: false, reason: "missing_text_or_filename" });
          return;
        }

        console.log(
          `[Capture BG] 📄  Saving transcript (${text.length} chars) → ${filename}`
        );

        // Build a data URL.  For large transcripts (>1 MB encoded) the
        // percent-encoded data URI can exceed Chrome's internal URL-length
        // limits, so we try a Blob URL first (works in modern Chrome SW)
        // and fall back to the data URI approach.
        let downloadUrl;
        try {
          // Preferred: Blob URL (handles any size, no encoding overhead)
          const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
          downloadUrl = URL.createObjectURL(blob);
        } catch {
          // Fallback: percent-encoded data URI
          downloadUrl = "data:text/plain;charset=utf-8," + encodeURIComponent(text);
        }

        // Suppress download UI
        try {
          await chrome.downloads.setUiOptions({ enabled: false });
        } catch { /* non-fatal if setUiOptions is unavailable */ }

        const downloadId = await new Promise((resolve, reject) => {
          chrome.downloads.download(
            { url: downloadUrl, filename, saveAs: false, conflictAction: "uniquify" },
            (id) => {
              if (chrome.runtime.lastError) {
                reject(new Error(chrome.runtime.lastError.message));
              } else {
                resolve(id);
              }
            }
          );
        });

        // Revoke Blob URL after download starts (with a small delay for safety)
        if (downloadUrl.startsWith("blob:")) {
          setTimeout(() => URL.revokeObjectURL(downloadUrl), 5000);
        }

        console.log(`[Capture BG] ✅  Transcript saved → ${filename}  (download #${downloadId})`);
        sendResponse({ success: true, downloadId, filename });
      } catch (err) {
        console.error(`[Capture BG] ❌ Transcript save error:`, err.message);
        sendResponse({ success: false, reason: err.message });
      }
    })();
    return true; // keep channel open for async response
  }

  // Only handle capture_request below; ignore everything else
  if (message.type !== "capture_request") return false;

  const { triggerType } = message;
  const now = Date.now();

  // ── Cooldown Guard ──
  if (now - lastCaptureTime < GLOBAL_COOLDOWN_MS) {
    const remaining = GLOBAL_COOLDOWN_MS - (now - lastCaptureTime);
    console.log(
      `[Capture BG] ⏳ Cooldown — skipping "${triggerType}" (${remaining} ms left)`
    );
    sendResponse({ success: false, reason: "cooldown" });
    return true;
  }

  // ── Resolve the sender tab ──
  const tabId = sender.tab?.id;
  if (!tabId) {
    console.warn("[Capture BG] No tab id on sender — ignoring.");
    sendResponse({ success: false, reason: "no_tab" });
    return true;
  }

  // Use an async wrapper so we can await and keep the message port open
  (async () => {
    try {
      // 1. Get the sender tab info
      const tab = await chrome.tabs.get(tabId);

      // 2. Skip restricted URLs that captureVisibleTab can't handle
      if (isRestrictedUrl(tab.url)) {
        console.log(`[Capture BG] Skipping restricted URL: ${tab.url}`);
        sendResponse({ success: false, reason: "restricted_url" });
        return;
      }

      // 3. Verify the sender tab is actually the active tab in its window.
      //    captureVisibleTab captures whatever is *visible*, so if our sender
      //    is a background tab we'd capture the wrong content.
      if (!tab.active) {
        console.log(
          `[Capture BG] Tab ${tabId} is not the active tab — skipping "${triggerType}"`
        );
        sendResponse({ success: false, reason: "tab_not_active" });
        return;
      }

      // 4. Capture the visible tab
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: "png",
      });

      // 5. Build filename:  InterestCapture/captures/<triggerType>_<ISO timestamp>.png
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      const filename = `InterestCapture/captures/${triggerType}_${timestamp}.png`;

      // 6. Ensure download UI stays suppressed (SW may have restarted)
      await chrome.downloads.setUiOptions({ enabled: false });

      // 7. Download — saveAs:false prevents the "Save As" dialog
      const downloadId = await new Promise((resolve, reject) => {
        chrome.downloads.download(
          { url: dataUrl, filename, saveAs: false, conflictAction: "uniquify" },
          (id) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
            } else {
              resolve(id);
            }
          }
        );
      });

      // ── Success ──
      lastCaptureTime = Date.now();
      captureStats[triggerType] = (captureStats[triggerType] || 0) + 1;

      console.log(
        `[Capture BG] ✅  "${triggerType}" → ${filename}  ` +
        `(download #${downloadId} | total: ${captureStats[triggerType]})`
      );
      sendResponse({ success: true, downloadId, filename });

    } catch (err) {
      console.error(`[Capture BG] ❌ Error for "${triggerType}":`, err.message);
      sendResponse({ success: false, reason: err.message });
    }
  })();

  // Return true to keep the message channel open for the async sendResponse
  return true;
});

// ── Service Worker Ready ─────────────────────────────────────────────────────
console.log("[Capture BG] Background service worker loaded — ready for capture requests.");

// ═══════════════════════════════════════════════════════════════════════════════
//  TAB AUDIO TRANSCRIPTION — Offscreen Document + chrome.tabCapture
// ═══════════════════════════════════════════════════════════════════════════════
//  chrome.tabCapture.getMediaStreamId() REQUIRES a user gesture (extension icon
//  click, keyboard shortcut, or context menu).  Auto-starting from content.js
//  is impossible — Chrome blocks it with "Extension has not been invoked".
//
//  Flow:
//    1. Content.js detects <video>/<audio> playing → sends "media_detected"
//    2. Background sets badge "▶" to hint the user to click the icon
//    3. User clicks extension icon → chrome.action.onClicked fires (user gesture!)
//    4. Background calls chrome.tabCapture.getMediaStreamId() (now allowed)
//    5. Background creates offscreen doc, sends streamId → offscreen.js
//    6. Offscreen runs SpeechRecognition on real tab audio
//    7. Transcript lines relay: offscreen → background → content.js
//    8. Click icon again → stops transcription
// ═══════════════════════════════════════════════════════════════════════════════

// Per-tab state
const tabState = {};  // tabId → { recording: bool, mediaTitle: string }
let offscreenDocCreated = false;

// ── Badge helpers ────────────────────────────────────────────────────────────
function setBadge(tabId, text, color) {
  chrome.action.setBadgeText({ text, tabId });
  chrome.action.setBadgeBackgroundColor({ color, tabId });
}

// ── Ensure offscreen document exists ─────────────────────────────────────────
async function ensureOffscreenDocument() {
  if (offscreenDocCreated) return;
  try {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ["OFFSCREEN_DOCUMENT"],
    });
    if (contexts.length > 0) { offscreenDocCreated = true; return; }
  } catch {}

  try {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA", "AUDIO_PLAYBACK"],
      justification:
        "Captures tab audio via SpeechRecognition in offscreen context.",
    });
    offscreenDocCreated = true;
    console.log("[Capture BG] 📄 Offscreen document created.");
  } catch (err) {
    if (err.message?.includes("single offscreen") || err.message?.includes("already")) {
      offscreenDocCreated = true;
    } else {
      throw err;
    }
  }
}

// ── Start transcription for a tab ────────────────────────────────────────────
async function startTranscription(tab) {
  const tabId = tab.id;
  try {
    await ensureOffscreenDocument();

    const streamId = await chrome.tabCapture.getMediaStreamId({
      targetTabId: tabId,
    });
    console.log(`[Capture BG] 🎧 Got tab audio streamId for tab ${tabId}.`);

    await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "start_transcription",
      streamId,
      tabId,
    });

    tabState[tabId] = {
      recording: true,
      mediaTitle: tabState[tabId]?.mediaTitle || tab.title || "",
    };
    setBadge(tabId, "REC", "#d93025");
    chrome.action.setTitle({
      tabId,
      title: "🔴 Recording — click to stop transcription",
    });

    // Tell the content script transcription started
    await chrome.tabs.sendMessage(tabId, {
      type: "transcription_started",
      title: tabState[tabId].mediaTitle,
    });

    console.log(`[Capture BG] 🎙️ Transcription STARTED for tab ${tabId}.`);
  } catch (err) {
    console.error("[Capture BG] ❌ Failed to start transcription:", err.message);
    setBadge(tabId, "ERR", "#d93025");
    try {
      await chrome.tabs.sendMessage(tabId, {
        type: "transcription_error",
        error: err.message,
      });
    } catch {}
  }
}

// ── Stop transcription for a tab ─────────────────────────────────────────────
async function stopTranscription(tabId, reason) {
  try {
    await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "stop_transcription",
      reason: reason || "user_stopped",
    });
  } catch {}
  if (tabState[tabId]) tabState[tabId].recording = false;
  setBadge(tabId, "", "#4285f4");
  chrome.action.setTitle({
    tabId,
    title: "Click to start tab audio transcription",
  });
  console.log(`[Capture BG] ⏹️ Transcription STOPPED for tab ${tabId} (${reason}).`);
}

// ══════════════════════════════════════════════════════════════════════════════
//  EXTENSION ICON CLICK — toggle transcription (user gesture = tabCapture OK)
// ══════════════════════════════════════════════════════════════════════════════
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab?.id) return;

  if (tabState[tab.id]?.recording) {
    // Currently recording → stop
    await stopTranscription(tab.id, "user_stopped");
  } else {
    // Not recording → start
    await startTranscription(tab);
  }
});

// ══════════════════════════════════════════════════════════════════════════════
//  MESSAGE RELAY:  content.js ↔ background.js ↔ offscreen.js
// ══════════════════════════════════════════════════════════════════════════════
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  // ── Messages FROM content.js ──────────────────────────────────────────────
  if (sender.tab) {
    const tabId = sender.tab.id;

    // Content.js detected media playing → set badge hint
    if (message.type === "media_detected") {
      if (!tabState[tabId]) tabState[tabId] = { recording: false, mediaTitle: "" };
      tabState[tabId].mediaTitle = message.title || sender.tab.title || "";
      if (!tabState[tabId].recording) {
        setBadge(tabId, "▶", "#4285f4");
        chrome.action.setTitle({
          tabId,
          title: `▶ Media detected — click to transcribe: "${tabState[tabId].mediaTitle}"`,
        });
      }
      return false;
    }

    // Content.js reports all media ended
    if (message.type === "media_ended") {
      if (tabState[tabId]?.recording) {
        stopTranscription(tabId, "media_ended");
      } else {
        setBadge(tabId, "", "#4285f4");
      }
      return false;
    }

    // Content.js wants to stop (page navigating away, etc.)
    if (message.type === "stop_tab_transcription") {
      if (tabState[tabId]?.recording) {
        stopTranscription(tabId, message.reason || "content_stop");
      }
      sendResponse({ success: true });
      return true;
    }

    return false; // let other listeners handle
  }

  // ── Messages FROM offscreen.js → relay to content.js ─────────────────────
  if (message.from === "offscreen") {
    // Find which tab is recording
    const tabId = Object.keys(tabState).find(
      (id) => tabState[id]?.recording
    );
    if (!tabId) return false;

    const numTabId = Number(tabId);

    const relayTypes = [
      "transcript_line",
      "transcription_started",
      "transcription_paused",
      "transcription_complete",
      "transcription_error",
    ];

    if (relayTypes.includes(message.type)) {
      (async () => {
        try {
          await chrome.tabs.sendMessage(numTabId, {
            type: message.type,
            time: message.time,
            text: message.text,
            confidence: message.confidence,
            transcript: message.transcript,
            lineCount: message.lineCount,
            totalLines: message.totalLines,
            error: message.error,
            reason: message.reason,
          });
        } catch (err) {
          console.warn("[Capture BG] Relay to tab failed:", err.message);
        }
      })();

      if (message.type === "transcription_complete") {
        console.log(
          `[Capture BG] 📄 Transcription complete for tab ${tabId} ` +
          `(${message.lineCount || 0} lines).`
        );
        if (tabState[numTabId]) tabState[numTabId].recording = false;
        setBadge(numTabId, "", "#4285f4");
        chrome.action.setTitle({
          tabId: numTabId,
          title: "Click to start tab audio transcription",
        });
      }
    }
    return false;
  }

  return false;
});

// ── Clean up when a tab is closed ────────────────────────────────────────────
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabState[tabId]?.recording) {
    stopTranscription(tabId, "tab_closed");
  }
  delete tabState[tabId];
});
