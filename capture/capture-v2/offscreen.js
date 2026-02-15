// =============================================================================
// offscreen.js — Offscreen Document for Tab Audio Playback
// =============================================================================
// This runs in an offscreen document created by background.js.
//
// Flow:
//   1. background.js sends { type: "start_transcription", streamId }
//   2. We call getUserMedia with chromeMediaSource:"tab" to get the tab's audio
//   3. We play the audio back through AudioContext so the user still hears it
//   4. Speech-to-text is handled separately by transcriber.js (MAIN WORLD)
//
// Why offscreen?
//   - chrome.tabCapture gives us the ACTUAL tab audio
//   - We play it back so the user continues hearing the tab's audio
//   - SpeechRecognition does NOT work in offscreen docs (no focus, no mic
//     permission prompt), so STT is handled in the page context instead
// =============================================================================

(() => {
  "use strict";

  let audioContext = null;
  let mediaStream = null;
  let isCapturing = false;

  // ── Listen for messages from background.js ─────────────────────────────────
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.target !== "offscreen") return false;

    switch (message.type) {
      case "start_transcription":
        handleStart(message.streamId);
        sendResponse({ success: true });
        return true;

      case "stop_transcription":
        handleStop(message.reason || "stopped");
        sendResponse({ success: true });
        return true;

      case "pause_transcription":
        handlePause();
        sendResponse({ success: true });
        return true;
    }
    return false;
  });

  // ── Start: get tab audio stream and play it back ───────────────────────────
  async function handleStart(streamId) {
    if (isCapturing) {
      console.log("[Offscreen] Already capturing audio, ignoring duplicate start.");
      return;
    }

    try {
      // 1. Get the tab's audio stream using the streamId from chrome.tabCapture
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          mandatory: {
            chromeMediaSource: "tab",
            chromeMediaSourceId: streamId,
          },
        },
        video: false,
      });

      const audioTracks = mediaStream.getAudioTracks();
      console.log(
        `[Offscreen] ✅ Got tab audio stream: ${audioTracks.length} track(s)`,
        audioTracks.map(t => `${t.label} (${t.readyState})`).join(", ")
      );

      // 2. Play audio back through AudioContext so user continues hearing it
      audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(mediaStream);
      source.connect(audioContext.destination);

      isCapturing = true;

      console.log("[Offscreen] 🔊 Tab audio capture STARTED — audio playing back.");

      chrome.runtime.sendMessage({
        from: "offscreen",
        type: "transcription_started",
      });

    } catch (err) {
      console.error("[Offscreen] ❌ Failed to start audio capture:", err);
      chrome.runtime.sendMessage({
        from: "offscreen",
        type: "transcription_error",
        error: err.message,
      });
    }
  }

  // ── Pause: keep stream alive but signal paused state ───────────────────────
  function handlePause() {
    console.log("[Offscreen] ⏸️ Audio capture pause requested.");
    chrome.runtime.sendMessage({
      from: "offscreen",
      type: "transcription_paused",
      transcript: [],
      lineCount: 0,
    });
  }

  // ── Stop: full cleanup ─────────────────────────────────────────────────────
  function handleStop(reason) {
    isCapturing = false;

    try { audioContext?.close(); } catch {}
    try { mediaStream?.getTracks().forEach(t => t.stop()); } catch {}

    audioContext = null;
    mediaStream = null;

    console.log(`[Offscreen] ⏹️ Audio capture STOPPED (${reason}).`);

    chrome.runtime.sendMessage({
      from: "offscreen",
      type: "transcription_complete",
      transcript: [],
      lineCount: 0,
      reason,
    });
  }

  console.log("[Offscreen] ✅ Offscreen audio capture document loaded and ready.");
})();
