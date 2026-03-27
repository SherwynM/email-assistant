# app.py — Render Backend for Email Research Workflow

from flask import Flask, request, jsonify
import requests
import os
import logging
import time
from functools import wraps

# ─── Logging setup (Step 6) ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── Config from environment only — never hardcode keys (Step 4) ─────────────
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")  # OAuth client ID for audience check
GEMINI_URL = (
    "https://generativelanguage.googleapis.com"
    "/v1beta/models/gemini-2.0-flash:generateContent"
)


# ─── Token verification with audience check (Step 3) ─────────────────────────
def verify_token(token):
    try:
        resp = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={token}",
            timeout=5
        )
        if resp.status_code != 200:
            return None, "Invalid token"

        data = resp.json()

        # Audience check — ensures token was issued to YOUR Google project
        if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
            logger.warning(f"Audience mismatch: {data.get('aud')}")
            return None, "Token audience mismatch"

        # Expiry check
        if int(data.get("exp", 0)) < time.time():
            return None, "Token expired"

        return data, None

    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        return None, str(e)


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing auth header"}), 401

        token = auth.split(" ", 1)[1]
        token_data, err = verify_token(token)

        if err:
            logger.warning(f"Auth rejected: {err}")
            return jsonify({"error": f"Unauthorized: {err}"}), 401

        request.user_email = token_data.get("email", "unknown")
        return f(*args, **kwargs)
    return wrapper


# ─── Gemini helper — body truncated to fix bandwidth quota error ──────────────
def call_gemini(prompt, max_tokens=400):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in environment")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.3
        }
    }

    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json=payload,
        timeout=30
    )

    if resp.status_code != 200:
        logger.error(f"Gemini error {resp.status_code}: {resp.text[:200]}")
        raise Exception(f"Gemini API error: {resp.status_code}")

    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "email-research-backend"})


@app.route("/classify", methods=["POST"])
@require_auth
def classify():
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    subject    = body.get("subject", "")
    email_body = body.get("body", "")[:800]  # Truncated to avoid bandwidth quota

    prompt = f"""Classify this email into exactly one of:
pitch_deck | vendor_proposal | client_brief | meeting_request | general_business

Subject: {subject}
Body excerpt: {email_body}

Reply with ONLY the label, nothing else."""

    try:
        result = call_gemini(prompt, max_tokens=10)
        logger.info(f"[{request.user_email}] classified: {result.strip()}")
        return jsonify({"type": result.strip()})
    except Exception as e:
        logger.error(f"classify error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/analyze", methods=["POST"])
@require_auth
def analyze():
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    subject    = body.get("subject", "")
    email_body = body.get("body", "")[:1200]  # Truncated
    sender     = body.get("sender", "")
    email_type = body.get("type", "general_business")

    prompt = f"""Analyze this email. Return ONLY valid JSON with these keys:
- summary (string): 2-3 sentence summary
- key_takeaway (string): one line
- risk_flags (list of strings): concerns, empty list if none
- suggested_action (string): recommended next step
- research_score (int): 1-10 confidence
- draft_reply (string): suggested reply text

From: {sender}
Subject: {subject}
Type: {email_type}
Body: {email_body}"""

    try:
        import json
        raw = call_gemini(prompt, max_tokens=600)

        try:
            result = json.loads(raw)
        except Exception:
            # Strip markdown fences if Gemini wraps JSON
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(cleaned)

        logger.info(f"[{request.user_email}] analyzed: {subject[:50]}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"analyze error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/draft", methods=["POST"])
@require_auth
def draft():
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    subject     = body.get("subject", "")
    email_body  = body.get("body", "")[:800]
    sender_name = body.get("sender_name", "")
    context     = body.get("context", "")

    prompt = f"""Write a short professional reply (3-5 sentences).

From: {sender_name}
Subject: {subject}
Body: {email_body}
Context: {context}

Write reply text only. No subject line."""

    try:
        result = call_gemini(prompt, max_tokens=250)
        logger.info(f"[{request.user_email}] draft reply generated")
        return jsonify({"draft": result.strip()})
    except Exception as e:
        logger.error(f"draft error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Error handlers ──────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500 error: {e}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
