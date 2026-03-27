// appsscript.gs — Apps Script frontend
// Calls your Render backend as a proxy. NO Gemini key stored here.

const BACKEND_URL = "https://your-render-app.onrender.com"; // ← Replace with your Render URL

// ─── Auth token ──────────────────────────────────────────────────────────────
function getAuthToken() {
  return ScriptApp.getIdentityToken(); // Google-issued token, verified by backend
}

// ─── Classify email type ─────────────────────────────────────────────────────
function classifyEmail(subject, body) {
  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/classify", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + getAuthToken()
      },
      payload: JSON.stringify({
        subject: subject,
        body: body.substring(0, 800) // Truncate on client side too
      }),
      muteHttpExceptions: true
    });

    var code = resp.getResponseCode();
    if (code !== 200) {
      Logger.log("classify failed: " + code + " " + resp.getContentText());
      return "general_business";
    }

    return JSON.parse(resp.getContentText()).type;
  } catch (e) {
    Logger.log("classifyEmail error: " + e);
    return "general_business";
  }
}

// ─── Analyze email ───────────────────────────────────────────────────────────
function analyzeEmail(subject, body, sender, type) {
  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + getAuthToken()
      },
      payload: JSON.stringify({
        subject: subject,
        body: body.substring(0, 1200),
        sender: sender,
        type: type
      }),
      muteHttpExceptions: true
    });

    var code = resp.getResponseCode();
    if (code !== 200) {
      Logger.log("analyze failed: " + code + " " + resp.getContentText());
      return null;
    }

    return JSON.parse(resp.getContentText());
  } catch (e) {
    Logger.log("analyzeEmail error: " + e);
    return null;
  }
}

// ─── Get draft reply ─────────────────────────────────────────────────────────
function getDraftReply(subject, body, senderName, context) {
  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/draft", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + getAuthToken()
      },
      payload: JSON.stringify({
        subject: subject,
        body: body.substring(0, 800),
        sender_name: senderName,
        context: context || ""
      }),
      muteHttpExceptions: true
    });

    var code = resp.getResponseCode();
    if (code !== 200) {
      Logger.log("draft failed: " + code + " " + resp.getContentText());
      return "";
    }

    return JSON.parse(resp.getContentText()).draft;
  } catch (e) {
    Logger.log("getDraftReply error: " + e);
    return "";
  }
}

// ─── One-time cleanup: remove Gemini key if accidentally saved ───────────────
function removeGeminiKeyFromProperties() {
  var props = PropertiesService.getScriptProperties();
  if (props.getProperty("GEMINI_API_KEY")) {
    props.deleteProperty("GEMINI_API_KEY");
    Logger.log("✓ GEMINI_API_KEY removed from Script Properties.");
  } else {
    Logger.log("✓ No GEMINI_API_KEY found. You're clean.");
  }
}

// ─── Health check — run this to verify backend is reachable ─────────────────
function checkBackendHealth() {
  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/health", {
      muteHttpExceptions: true
    });
    Logger.log("Backend status: " + resp.getResponseCode() + " " + resp.getContentText());
  } catch (e) {
    Logger.log("Backend unreachable: " + e);
  }
}
