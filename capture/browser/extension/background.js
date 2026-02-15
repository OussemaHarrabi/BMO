// =============================================================================
// background.js — Service Worker  (Manifest V3)
// =============================================================================
// Responsibilities:
//   1. Listen for "capture_request" messages from content.js.
//   2. Verify the requesting tab is the active tab in its window.
//   3. Use chrome.tabs.captureVisibleTab() to grab a PNG screenshot.
//   4. Send screenshot to BMO API for processing.
//   5. Fallback to local storage if API is unavailable.
//   6. Enforce a server-side 3 s cooldown (belt-and-suspenders with content.js).
// =============================================================================

// ── API Configuration ──────────────────────────────────────────────────────
// Default API URL - can be overridden via chrome.storage.sync
const DEFAULT_BMO_API_URL = "http://localhost:8000/api/capture";
let BMO_API_URL = DEFAULT_BMO_API_URL;

// Load API URL from storage on startup
chrome.storage.sync.get(["bmo_api_url"], (result) => {
  if (result.bmo_api_url) {
    BMO_API_URL = result.bmo_api_url;
    console.log("[Capture BG] Loaded custom API URL:", BMO_API_URL);
  }
});

// Listen for storage changes to update API URL dynamically
chrome.storage.onChanged.addListener((changes, namespace) => {
  if (namespace === "sync" && changes.bmo_api_url) {
    BMO_API_URL = changes.bmo_api_url.newValue || DEFAULT_BMO_API_URL;
    console.log("[Capture BG] API URL updated:", BMO_API_URL);
  }
});

// Handle messages to get/set configuration
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "get_config") {
    sendResponse({ bmo_api_url: BMO_API_URL });
    return true;
  }
  
  if (message.type === "set_config") {
    if (message.bmo_api_url) {
      chrome.storage.sync.set({ bmo_api_url: message.bmo_api_url }, () => {
        BMO_API_URL = message.bmo_api_url;
        console.log("[Capture BG] Config updated:", message.bmo_api_url);
        sendResponse({ success: true });
      });
      return true;
    }
    sendResponse({ success: false, error: "No bmo_api_url provided" });
    return true;
  }
  
  // Continue to capture_request handler below
  return false;
});

// ── Suppress Chrome's download UI (for fallback saves) ──────────────────────
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
const captureStats = {
  apiSuccess: 0,
  apiFailed: 0,
  localFallback: 0
};

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

// ── Send to BMO API ──────────────────────────────────────────────────────────
async function sendToAPI(dataUrl, triggerType, sourceUrl) {
  // Extract base64 data (remove data:image/png;base64, prefix)
  const base64Data = dataUrl.replace(/^data:image\/\w+;base64,/, "");
  
  const payload = {
    trigger_type: triggerType,
    timestamp: new Date().toISOString(),
    source_url: sourceUrl || null,
    screenshot_base64: base64Data,
    metadata: {
      extension_version: chrome.runtime.getManifest().version
    }
  };
  
  const response = await fetch(`${BMO_API_URL}/event`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  
  if (!response.ok) {
    throw new Error(`API returned ${response.status}`);
  }
  
  return await response.json();
}

// ── Fallback: Save locally ───────────────────────────────────────────────────
async function saveLocally(dataUrl, triggerType) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = `captures/${triggerType}_${timestamp}.png`;
  
  await chrome.downloads.setUiOptions({ enabled: false });
  
  return new Promise((resolve, reject) => {
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
}

// ── Message Handler ──────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
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

  (async () => {
    try {
      const tab = await chrome.tabs.get(tabId);

      if (isRestrictedUrl(tab.url)) {
        console.log(`[Capture BG] Skipping restricted URL: ${tab.url}`);
        sendResponse({ success: false, reason: "restricted_url" });
        return;
      }

      if (!tab.active) {
        console.log(
          `[Capture BG] Tab ${tabId} is not the active tab — skipping "${triggerType}"`
        );
        sendResponse({ success: false, reason: "tab_not_active" });
        return;
      }

      // Capture the visible tab
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: "png",
      });

      lastCaptureTime = Date.now();
      
      // Try to send to BMO API
      try {
        const result = await sendToAPI(dataUrl, triggerType, tab.url);
        captureStats.apiSuccess++;
        
        console.log(
          `[Capture BG] ✅ API success "${triggerType}" → event_id: ${result.event_id} ` +
          `(total: ${captureStats.apiSuccess})`
        );
        sendResponse({ success: true, event_id: result.event_id, method: "api" });
        
      } catch (apiError) {
        // Fallback to local storage
        console.warn(`[Capture BG] API failed: ${apiError.message}, falling back to local`);
        captureStats.apiFailed++;
        
        try {
          const downloadId = await saveLocally(dataUrl, triggerType);
          captureStats.localFallback++;
          
          console.log(
            `[Capture BG] 📁 Local fallback "${triggerType}" → download #${downloadId}`
          );
          sendResponse({ success: true, downloadId, method: "local" });
          
        } catch (localError) {
          console.error(`[Capture BG] ❌ Both API and local failed:`, localError.message);
          sendResponse({ success: false, reason: localError.message });
        }
      }

    } catch (err) {
      console.error(`[Capture BG] ❌ Error for "${triggerType}":`, err.message);
      sendResponse({ success: false, reason: err.message });
    }
  })();

  return true;
});

// ── Service Worker Ready ─────────────────────────────────────────────────────
console.log("[Capture BG] Background service worker loaded — ready for capture requests.");
console.log(`[Capture BG] API endpoint: ${BMO_API_URL}`);
