# app.py — Render Backend for Email Research Workflow

from flask import Flask, request, jsonify
import requests
import os
import logging
import time
from functools import wraps

# ─── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── Config from environment only — never hardcode keys ──────────────────────
# NEW
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GROQ_URL         = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL       = "llama-3.3-70b-versatile"

# ─── Token verification ───────────────────────────────────────────────────────
def verify_token(token):
    try:
        resp = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={token}",
            timeout=5
        )
        if resp.status_code != 200:
            return None, "Invalid token"

        data = resp.json()

        # Audience check — only enforced if GOOGLE_CLIENT_ID is set
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


# ─── Gemini helper with retry on 429 ─────────────────────────────────────────
def call_groq(prompt, max_tokens=1024, retries=2, retry_delay=5):
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set in environment")

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    for attempt in range(retries):
        resp = requests.post(
            GROQ_URL,
            json=payload,
            headers=headers,
            timeout=30
        )

        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]

        if resp.status_code == 429:
            logger.warning(f"Groq quota hit (attempt {attempt + 1}/{retries}), retrying in {retry_delay}s...")
            if attempt < retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise Exception("Groq quota exceeded. Try again shortly.")

        logger.error(f"Groq error {resp.status_code}: {resp.text[:200]}")
        raise Exception(f"Groq API error: {resp.status_code}")

    raise Exception("Groq call failed after retries")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "email-research-backend"})


@app.route("/process", methods=["POST"])
@require_auth
def process():
    """Single endpoint for all Gmail Add-on tasks"""
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    task       = body.get("task", "")
    email_body = body.get("body", "")[:2000]  # Truncated to avoid bandwidth quota

    prompts = {
        "summarize": (
            "Summarize the following email clearly and concisely in 3 to 5 bullet points. "
            "Focus on the key message, action items, deadlines, and important details.\n\n"
            "Email:\n" + email_body
        ),
        "translate": (
            "Translate the following email into Konkani using Devanagari script. "
            "Preserve the original tone and meaning.\n\n"
            "Email:\n" + email_body
        ),
        "grammar": (
            "Check the following email for grammar and spelling mistakes. "
            "For each issue, respond in this format:\n"
            "Incorrect: ...\nCorrect: ...\nReason: ...\n\n"
            "If there are no errors, say: No errors found — the email looks good.\n\n"
            "Email:\n" + email_body
        ),
        "sentiment": (
            "Analyze the sentiment of the following email and respond with:\n"
            "1. Overall Sentiment\n"
            "2. Confidence\n"
            "3. Emotional Tones\n"
            "4. One-sentence Tone Summary\n"
            "5. Suggested Reply Tone\n\n"
            "Email:\n" + email_body
        )
    }

    prompt = prompts.get(task)
    if not prompt:
        return jsonify({"error": f"Unknown task: {task}"}), 400

    try:
        result = call_groq(prompt, max_tokens=1024)
        logger.info(f"[{request.user_email}] task={task} completed")
        return jsonify({"result": result})
    except Exception as e:
        logger.error(f"process error task={task}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/classify", methods=["POST"])
@require_auth
def classify():
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    subject    = body.get("subject", "")
    email_body = body.get("body", "")[:800]

    prompt = (
        "Classify this email into exactly one of:\n"
        "pitch_deck | vendor_proposal | client_brief | meeting_request | general_business\n\n"
        f"Subject: {subject}\nBody excerpt: {email_body}\n\n"
        "Reply with ONLY the label."
    )

    try:
        result = call_groq(prompt, max_tokens=10)
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

    import json as json_lib
    subject    = body.get("subject", "")
    email_body = body.get("body", "")[:1200]
    sender     = body.get("sender", "")
    email_type = body.get("type", "general_business")

    prompt = (
        "Analyze this email. Return ONLY valid JSON with keys:\n"
        "summary, key_takeaway, risk_flags (list), suggested_action, "
        "research_score (1-10), draft_reply\n\n"
        f"From: {sender}\nSubject: {subject}\nType: {email_type}\nBody: {email_body}"
    )

    try:
        raw = call_groq(prompt, max_tokens=600)
        try:
            result = json_lib.loads(raw)
        except Exception:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json_lib.loads(cleaned)
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

    prompt = (
        f"Write a short professional reply (3-5 sentences).\n\n"
        f"From: {sender_name}\nSubject: {subject}\nBody: {email_body}\nContext: {context}\n\n"
        "Write reply text only. No subject line."
    )

    try:
        result = call_groq(prompt, max_tokens=250)
        return jsonify({"draft": result.strip()})
    except Exception as e:
        logger.error(f"draft error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Error handlers ───────────────────────────────────────────────────────────
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
