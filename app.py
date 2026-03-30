# app.py — Render Backend for Email Assistant

from flask import Flask, request, jsonify
import requests
import os
import logging
import time
import json as json_lib
from functools import wraps

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

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

        if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
            logger.warning(f"Audience mismatch: {data.get('aud')}")
            return None, "Token audience mismatch"

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


# ─── Groq helper with retry on 429 ───────────────────────────────────────────
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
        resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)

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


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "email-assistant-backend"})


@app.route("/process", methods=["POST"])
@require_auth
def process():
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    task       = body.get("task", "")
    email_body = body.get("body", "")[:2000]

    prompts = {
        "summarize": (
            "Summarize the following email professionally using this exact format:\n\n"
            "**📋 Email Summary**\n\n"
            "**Overview**\n"
            "[One concise sentence describing the purpose of the email]\n\n"
            "**Key Points**\n"
            "• [Key point 1]\n"
            "• [Key point 2]\n"
            "• [Key point 3]\n\n"
            "**Action Items** (only include if present in the email)\n"
            "• [Person] — [Task] (Due: [Date])\n\n"
            "**Next Steps** (only include if applicable)\n"
            "[What the recipient should do next]\n\n"
            "Rules: Only include sections relevant to the email. "
            "Keep bullet points concise. Do not add commentary outside the format.\n\n"
            "Email:\n" + email_body
        ),
        "translate": (
            "Translate the following email into Konkani using Roman script (Romi Konkani) ONLY. "
            "Use English alphabet letters exclusively — do NOT use Devanagari script or any other script. "
            "Write all Konkani words phonetically using Roman letters. "
            "Preserve the original tone, structure, and paragraph breaks exactly as they appear in the email. "
            "Add a blank line between each paragraph, matching the original layout.\n\n"
            "Email:\n" + email_body
        ),
        "grammar": (
            "Check the following email for genuine grammar and spelling mistakes only. "
            "Use this exact format for each issue:\n\n"
            "**Issue [number]**\n"
            "Incorrect: [original text]\n"
            "Correct: [corrected text]\n"
            "Reason: [brief explanation]\n\n"
            "Strict rules you MUST follow:\n"
            "- Do NOT flag proper nouns, brand names, company names, product names, or event names "
            "(e.g. TechInnovate, DataInsight Corp, AI-Powered Automation) — these are intentional and correct.\n"
            "- Do NOT flag email salutations (e.g. 'Hello All,', 'Hi Team,', 'Dear Sherwyn,') — "
            "the comma after a salutation is correct email convention, never flag it.\n"
            "- Do NOT flag email sign-offs or complimentary closes (e.g. 'All the best,', 'Best regards,', "
            "'Sincerely,', 'Cheers,') — the comma after a sign-off is correct convention, never flag it.\n"
            "- Do NOT flag informal contractions (e.g. I'm, Let's, There's) as errors in a business email "
            "unless the email is strictly formal in tone throughout.\n"
            "- Do NOT flag style preferences, punctuation inside action item lists, or subjective word choices.\n"
            "- Only flag clear, objective grammatical errors and definite spelling mistakes.\n"
            "- Separate each issue with a blank line.\n"
            "- If there are no real errors, respond with exactly:\n"
            "**✅ No errors found — the email is well written.**\n\n"
            "Email:\n" + email_body
        ),
        "sentiment": (
            "Analyze the sentiment of the following email using this exact format:\n\n"
            "**📊 Sentiment Analysis**\n\n"
            "**Overall Sentiment:** [Positive / Negative / Neutral / Mixed]\n"
            "**Confidence Level:** [High / Medium / Low]\n\n"
            "**Emotional Tones**\n"
            "• [Tone 1]\n"
            "• [Tone 2]\n"
            "• [Tone 3]\n\n"
            "**Tone Summary**\n"
            "[One clear sentence describing the overall emotional tone]\n\n"
            "**Suggested Reply Tone**\n"
            "[How the recipient should respond — e.g. professional and reassuring]\n\n"
            "**Sample Reply Opener**\n"
            "[One example opening sentence for a reply]\n\n"
            "Do not add commentary outside this format.\n\n"
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
        "Classify this email into exactly one of these labels:\n"
        "pitch_deck | vendor_proposal | client_brief | meeting_request | general_business\n\n"
        f"Subject: {subject}\nBody excerpt: {email_body}\n\n"
        "Reply with ONLY the label. No explanation."
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

    subject    = body.get("subject", "")
    email_body = body.get("body", "")[:1200]
    sender     = body.get("sender", "")
    email_type = body.get("type", "general_business")

    prompt = (
        "Analyze this email and return ONLY valid JSON with exactly these keys:\n"
        "{\n"
        '  "type": "one of: pitch_deck | vendor_proposal | client_brief | meeting_request | general_business",\n'
        '  "summary": "1-2 sentence overview of the email",\n'
        '  "key_takeaway": "the single most important point from this email",\n'
        '  "risk_flags": ["concern 1", "concern 2"],\n'
        '  "suggested_action": "what the recipient should do next",\n'
        '  "research_score": 8,\n'
        '  "draft_reply": "short professional reply of 3-4 sentences, no subject line"\n'
        "}\n\n"
        "Rules: Return raw JSON only. No markdown fences. No explanation outside the JSON.\n\n"
        f"From: {sender}\nSubject: {subject}\nEmail Type: {email_type}\nBody: {email_body}"
    )

    try:
        raw = call_groq(prompt, max_tokens=700)
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
        f"Write a short professional email reply of 3-5 sentences.\n\n"
        f"From: {sender_name}\nSubject: {subject}\nBody: {email_body}\nContext: {context}\n\n"
        "Reply text only. No subject line. No sign-off needed."
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
