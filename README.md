# 📧 Email Assistant — Gmail Add-on

> AI-powered email tools built directly into Gmail. Summarize, translate, analyse sentiment, and get deep email insights — all with a single click, without leaving your inbox.

![Google Apps Script](https://img.shields.io/badge/Google%20Apps%20Script-V8-4285F4?style=flat&logo=google&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Backend-000000?style=flat&logo=flask&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036?style=flat)
![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?style=flat&logo=render&logoColor=white)

---

## Table of Contents

- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Setup & Deployment](#setup--deployment)
- [API Reference](#api-reference)
- [Security](#security)
- [Key Decisions](#key-decisions)

---

## What It Does

Open any email in Gmail → click a button in the sidebar → get instant AI-powered insights.

| Feature | Description |
|---|---|
| 📋 **Summarize Email** | Structured summary — overview, key points, action items, next steps |
| 🌐 **Translate to Konkani** | Translates email to Romi Konkani (Roman script), paragraph structure preserved |
| 📊 **Sentiment Analysis** | Emotional tone, confidence level, suggested reply tone + sample opener |
| 🔍 **Analyze Email** | Deep analysis — email type, clarity score, key takeaway, risk flags |
| ✉️ **Draft Reply** | One-tap professional reply draft, surfaced via a dedicated button after analysis |

---

## Architecture

The system is split across three distinct layers. Each layer has one job and communicates only with the layer directly adjacent to it.

```
┌─────────────────────────────────────────────────────┐
│         Layer 1 — Gmail Add-on (code.gs)            │
│   Google Apps Script · Renders UI · Reads email     │
└────────────────────┬────────────────────────────────┘
                     │  HTTPS POST + Bearer Token
┌────────────────────▼────────────────────────────────┐
│      Layer 2 — Flask Backend (app.py on Render)     │
│  Verifies token · Builds prompts · Calls Groq API   │
└────────────────────┬────────────────────────────────┘
                     │  REST API call with API Key
┌────────────────────▼────────────────────────────────┐
│           Layer 3 — Groq API (Llama 3.3 70B)        │
│     LLM Inference · Returns AI-generated text       │
└─────────────────────────────────────────────────────┘
```

### End-to-End Request Flow

1. User clicks a button (e.g. "Summarize Email") in the Gmail sidebar
2. `code.gs` reads the email — body (up to 3000 chars), subject, and sender
3. `code.gs` sends a `POST` to Render with `{ task, body }` + Google identity token in the `Authorization` header
4. `app.py` verifies the token against `oauth2.googleapis.com/tokeninfo` — rejects with 401 if invalid or expired
5. `app.py` picks the correct prompt from its prompts dictionary and appends the email body
6. `app.py` calls the Groq API with `model=llama-3.3-70b-versatile`, `temperature=0.3`, `max_tokens=1024`
7. Groq returns the AI-generated text; `app.py` extracts it and sends back `{ "result": "..." }`
8. `code.gs` renders the result as a formatted Gmail sidebar card

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| Frontend / UI | Google Apps Script (V8) | Gmail sidebar UI, email reading, backend communication |
| Backend / Logic | Python 3 + Flask | Token verification, prompt construction, Groq API calls |
| AI / Inference | Groq API — Llama 3.3 70B | All AI processing (summarise, translate, sentiment, analyse) |
| Deployment | Render (Free Tier) | Hosts the Flask backend, auto-deploys on push |
| Auth | Google OAuth 2.0 | Identity token verification on every request |
| State | Apps Script CacheService | Holds draft reply for 10 min between Analyze → Draft Reply button |

**Backend dependencies (`requirements.txt`):**
```
flask       # Web framework
requests    # HTTP calls to Google OAuth + Groq
gunicorn    # Production WSGI server for Render
```

No database. No external storage. The backend is fully stateless — every request is self-contained.

---

## Features

### 📋 Summarize Email
Calls `/process` with `task=summarize`. Returns a structured summary with four sections:
- **Overview** — one-sentence purpose
- **Key Points** — bullet list of the most important information
- **Action Items** — person → task → due date (only if present)
- **Next Steps** — what should happen next (only if applicable)

Sections are suppressed if not relevant to the email.

---

### 🌐 Translate to Romi Konkani
Calls `/process` with `task=translate`. Translates the email into **Romi Konkani** — Konkani written in Roman (English alphabet) script, not Devanagari. Paragraph breaks and blank lines from the original email are preserved exactly.

Romi Konkani was chosen because it is the traditionally written form used by the Goan Catholic community and is more accessible than Devanagari for many Konkani speakers.

---

### 📊 Sentiment Analysis
Calls `/process` with `task=sentiment`. Returns:
- **Overall Sentiment** — Positive / Negative / Neutral / Mixed
- **Confidence Level** — High / Medium / Low
- **Emotional Tones** — bullet list
- **Tone Summary** — one clear sentence
- **Suggested Reply Tone** — how the recipient should respond
- **Sample Reply Opener** — example opening sentence

---

### 🔍 Analyze Email + ✉️ Draft Reply
Calls `/analyze`. Unlike the other features, this route returns **structured JSON** with:

```json
{
  "type": "meeting_request",
  "summary": "...",
  "key_takeaway": "...",
  "risk_flags": ["...", "..."],
  "suggested_action": "...",
  "research_score": 8,
  "draft_reply": "..."
}
```

The `draft_reply` field is stored in `CacheService` (10-min TTL) and only surfaced when the user taps the **✉️ Draft Reply** button — keeping the analysis card clean.

---

## How It Works

### Prompt Construction
All prompts are stored in a Python dictionary inside the `/process` route. The task name is the key. The email body is appended at the end.

```python
prompts = {
    "summarize": (
        "Summarize the following email professionally...\n\n"
        "Email:\n" + email_body
    ),
    "translate": (
        "Translate into Romi Konkani (Roman script only)...\n\n"
        "Email:\n" + email_body
    ),
    "sentiment": (
        "Analyze the sentiment...\n\n"
        "Email:\n" + email_body
    )
}
prompt = prompts.get(task)
```

### Groq API Call
```python
payload = {
    "model": "llama-3.3-70b-versatile",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 1024,
    "temperature": 0.3  # low = consistent, structured output
}
resp = requests.post(GROQ_URL, json=payload, headers=headers)
return resp.json()["choices"][0]["message"]["content"]
```

### Token Verification
```python
def verify_token(token):
    resp = requests.get(
        f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
    )
    data = resp.json()
    if int(data.get("exp", 0)) < time.time():
        return None, "Token expired"
    return data, None
```

### Draft Reply Cache
```javascript
// Store after Analyze (10 min TTL)
CacheService.getUserCache().put('last_draft_reply', data.draft_reply, 600);

// Retrieve when button is tapped
function showDraftReply(e) {
  var draft = CacheService.getUserCache().get('last_draft_reply');
  return pushCardResult('✉️ Draft Reply', draft);
}
```

---

## Project Structure

```
── Google Apps Script (script.google.com) ──
code.gs              # Main add-on file — UI, routing, card rendering
appsscript.json      # Add-on manifest — scopes, triggers, metadata

── Render (this repo) ──
app.py               # Flask backend — all routes and logic
requirements.txt     # Python dependencies
Procfile             # web: gunicorn app:app

── Render Environment Variables ──
GROQ_API_KEY         # Groq API key — never in code
GOOGLE_CLIENT_ID     # Optional: enforces token audience check

── Apps Script Script Properties ──
Insights             # Your Render backend URL
```

---

## Setup & Deployment

### 1. Backend — Deploy to Render

1. Fork or clone this repo
2. Create a new **Web Service** on [Render](https://render.com)
3. Connect your GitHub repo
4. Set the following environment variables in Render:
   - `GROQ_API_KEY` — get yours free at [console.groq.com](https://console.groq.com)
   - `GOOGLE_CLIENT_ID` — optional, from Google Cloud Console
5. Render will auto-deploy using the `Procfile` (`gunicorn app:app`)
6. Copy your Render URL (e.g. `https://your-app.onrender.com`)

### 2. Frontend — Google Apps Script

1. Open [script.google.com](https://script.google.com) and create a new project
2. Paste `code.gs` into the editor
3. Replace `appsscript.json` with the provided manifest
4. Go to **Project Settings → Script Properties** and add:
   - Key: `Insights` → Value: your Render URL
5. Click **Deploy → New Deployment → Gmail Add-on**
6. Install the add-on on your Google account

### 3. Keep Render Warm (Important!)

Render's free tier spins down after ~15 minutes of inactivity. Run this once from the Apps Script editor to set up an automatic keep-warm ping every 14 minutes:

```javascript
setupKeepWarmTrigger()  // Run this once from the Apps Script editor
```

This prevents the cold-start timeout error when clicking buttons in Gmail.

### 4. Verify It's Working

Run `checkBackendHealth()` from the Apps Script editor. You should see `200 {"status": "ok"}` in the logs.

---

## API Reference

| Route | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | None | Health check — returns `{"status": "ok"}` |
| `/process` | POST | Bearer token | Handles summarize, translate, sentiment |
| `/analyze` | POST | Bearer token | Deep analysis — returns structured JSON |
| `/classify` | POST | Bearer token | Classifies email type (meeting, vendor, etc.) |
| `/draft` | POST | Bearer token | Standalone draft reply generation |

> **Note:** `/classify` and `/draft` are implemented on the backend but not currently exposed in the add-on UI. Available for future feature expansion with no backend changes needed.

**Request format for `/process`:**
```json
{
  "task": "summarize",
  "body": "email body text here..."
}
```

**Request format for `/analyze`:**
```json
{
  "subject": "Meeting Follow-up",
  "body": "email body text here...",
  "sender": "john@example.com"
}
```

---

## Security

| Principle | Implementation |
|---|---|
| **No keys in frontend** | Groq API key is a Render environment variable only — never in `code.gs` |
| **Google token auth** | Every request carries a Google-issued identity token verified against Google's OAuth2 endpoint |
| **Token expiry check** | The `exp` field is checked on every request — expired tokens are rejected |
| **Input truncation** | Email bodies are capped at 2000–3000 chars before transmission |
| **No data storage** | The backend stores nothing — no emails, no user data, no logs with content |
| **HTTPS only** | All communication (Apps Script → Render → Groq) is over HTTPS |

---

## Key Decisions

| Decision | What Was Chosen | Why |
|---|---|---|
| AI Provider | Groq API (migrated from Gemini) | Gemini hit 15 RPM limit frequently. Groq gives 30 RPM with faster, more reliable responses on the free tier. |
| LLM Model | Llama 3.3 70B Versatile | Best capability-to-speed ratio on Groq's free tier. Handles all four task types reliably. |
| Grammar Check | Feature removed entirely | The model consistently flagged valid Indian English constructions as errors (salutation commas, regional date formats, proper nouns). Unfixable via prompting — removal was the pragmatic call. |
| Konkani Script | Roman script (Romi Konkani) | Devanagari is generated by default but inaccessible to many Konkani speakers. Romi Konkani is the traditional written form for the Goan Catholic community. |
| Draft Reply UX | Separate button, not inline | Inline draft made the Analyze card too long. CacheService keeps the draft accessible without cluttering the main output. |
| Hosting | Render (free tier) | Zero cost, Python/Flask native support, auto-deploy from Git, HTTPS out of the box. |
| Output formatting | Prompt-enforced `**bold**` + `sanitizeForCard()` | Gmail card widgets support limited HTML. Using bold markers in prompts and converting them in the sanitizer gives clean formatted output without complex parsing logic. |

---

## Built By

**Sherwyn Misquitta** — MSc Data Science
March 2026

---

*Google Apps Script · Python Flask · Groq API (Llama 3.3 70B) · Render · Google OAuth 2.0*
