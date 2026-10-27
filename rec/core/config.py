"""
config.py — Runtime configuration loader for rec.

Reads all application configuration from environment variables, optionally
bootstrapping them from a .env file when ENV_FILE_PATH points to one (the
container mounts /home/bharani/fin-config/.env from the host at that path).
"""

import os

from dotenv import load_dotenv

env_file_path = os.getenv("ENV_FILE_PATH")
if env_file_path:
    load_dotenv(dotenv_path=env_file_path)
else:
    load_dotenv()

# ---------------------------------------------------------------------------
# Infisical / Gmail credential indirection
# ---------------------------------------------------------------------------

# Section name in api_keys.ini for the Infisical project holding Gmail creds.
key_gmail_infisical_section = os.getenv("key_gmail_infisical_section")

# These hold SECRET NAMES to look up in Infisical, not the values themselves.
key_gmail_username = os.getenv("key_gmail_username")
key_gmail_app_password = os.getenv("key_gmail_app_password")

# ---------------------------------------------------------------------------
# Gmail IMAP/SMTP endpoints
# ---------------------------------------------------------------------------

IMAP_HOST = os.getenv("imap_host", "imap.gmail.com")
SMTP_HOST = os.getenv("smtp_host", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("smtp_port", "587"))

# ---------------------------------------------------------------------------
# Application behavior
# ---------------------------------------------------------------------------

# Watched label for incoming receipts, and the label a message is moved to
# once successfully forwarded (visible in Gmail itself as the processed marker,
# in addition to the local dedup state file).
GMAIL_LABEL_IN = os.getenv("gmail_label_in", "Receipts/In")
GMAIL_LABEL_OUT = os.getenv("gmail_label_out", "Receipts/Out")

# Manual trigger: any Inbox message whose subject contains this literal
# marker is forwarded too, alongside anything under GMAIL_LABEL_IN - for
# messages that are awkward to label directly. Also the prefix rec itself
# puts on every subject it forwards.
SUBJECT_TRIGGER = os.getenv("subject_trigger", "[rec]")
DEST_EMAIL = os.getenv("dest_email")
POLL_SECONDS = int(os.getenv("poll_seconds", "300"))
TEST_MODE = os.getenv("test_mode", "false").lower() in ("true", "1", "t")

DEDUP_STATE_PATH = os.getenv("dedup_state_path", "/app/state/dedup_state.json")
HEARTBEAT_PATH = os.getenv("heartbeat_path", "/app/state/heartbeat")

# ---------------------------------------------------------------------------
# Optional HTTP upload channel (see rec/http_server.py)
# ---------------------------------------------------------------------------

# Off by default — the Gmail/IMAP poll loop is the primary ingress. When on,
# rec also listens for authenticated "POST /upload" requests carrying a receipt
# photo (e.g. from a phone automation) and feeds them through the same
# normalize-to-PDF + SMTP-forward pipeline as an emailed attachment.
HTTP_ENABLED = os.getenv("http_enabled", "false").lower() in ("true", "1", "t")
HTTP_BIND = os.getenv("http_bind", "0.0.0.0")
HTTP_PORT = int(os.getenv("http_port", "8080"))
# The single accepted upload path. Defaults to the obvious "/upload", but when
# the endpoint sits behind a public reverse proxy (e.g. a Cloudflare Tunnel
# hostname with bot-challenge middleware skipped only for one exact path) this
# can be set to an unguessable value instead, so a scanner hitting the
# well-known path never even reaches the bearer-token check.
HTTP_UPLOAD_PATH = "/" + os.getenv("http_upload_path", "upload").strip("/")
HTTP_MAX_UPLOAD_BYTES = int(os.getenv("http_max_upload_bytes", str(25 * 1024 * 1024)))
# How long the handler waits for the poll-loop thread to render + send before
# returning 504 (the upload still completes server-side). Padded above the
# bare render+SMTP cost to leave room for an OpenAI classification call
# (network + a cloud model, not the local-hardware minutes-per-receipt an
# Ollama vision model would cost — this isn't sized for that).
HTTP_RESULT_TIMEOUT = int(os.getenv("http_result_timeout", "120"))

# Bearer token for "POST /upload" — a SECRET NAME looked up in Infisical (same
# indirection as the Gmail creds), not the value itself. Defaults to reusing
# the Gmail Infisical section.
key_http_infisical_section = os.getenv("key_http_infisical_section") or key_gmail_infisical_section
key_http_token = os.getenv("key_http_token", "rec-http-token")

# ---------------------------------------------------------------------------
# OpenAI-based receipt categorization (optional, on top of OCR)
# ---------------------------------------------------------------------------

# Off by default. Tesseract/pypdf already extract vendor/amount/currency
# reasonably well via regex heuristics (see ocr.py); what they can't do is
# understand what was actually *purchased* - classify_category only pattern-
# matches a fixed keyword list, so a receipt line has to literally contain one
# of the listed words to resolve to anything but "misc". When on,
# llm_classify.py reads the OCR'd text and asks a model to read the itemized
# line items the way a human would; build_filename prefers its vendor/
# category/currency/amount over the regex path, field by field, falling back
# to the existing heuristics for anything it didn't return.
OPENAI_ENABLED = os.getenv("openai_enabled", "false").lower() in ("true", "1", "t")
# Verify this against platform.openai.com's current pricing/model list before
# relying on it — names and what's cheapest shift over time.
OPENAI_MODEL = os.getenv("openai_model", "gpt-4o-mini")
OPENAI_TIMEOUT = int(os.getenv("openai_timeout", "30"))
# Comma-separated and deliberately configurable (the whole point is picking
# categories finer-grained than OCR's fixed keyword-matched list, e.g.
# splitting "coffee" and "water" out of a single "meal" bucket).
RECEIPT_CATEGORIES = [
    c.strip()
    for c in os.getenv(
        "receipt_categories",
        "coffee,water,meal,taxi,train,flight,hotel,fuel,seats,statement,misc",
    ).split(",")
    if c.strip()
]

# Unlike the Gmail/HTTP secrets below, this is read directly from the process
# environment rather than Infisical — there's no Infisical entry set up for
# it. The actual value still never lives in git or a tracked .env: it's
# delivered via a host-side secrets env_file (same /home/bharani/secrets/
# convention the bek42/containers repo already uses for e.g. Cloudflare
# tokens), not the mounted fin-config .env.
OPENAI_API_KEY = os.getenv("openai_api_key")

# ---------------------------------------------------------------------------
# OCR (Tesseract) + PDF text extraction — receipt content -> output filename
# ---------------------------------------------------------------------------

# When on, forwarded receipt *images* are run through Tesseract and PDF
# attachments have their text layer read, and the output PDF filename is built
# from the recognised content (vendor / category / currency / amount) instead of
# the subject regex. Any OCR/parse failure degrades silently to the sender +
# subject/body fallback.
OCR_ENABLED = os.getenv("ocr_enabled", "true").lower() in ("true", "1", "t")

# '+'-joined Tesseract language codes; needs the matching tesseract-ocr-<lang>
# packages installed (see docker/Dockerfile.debian).
OCR_LANGS = os.getenv("ocr_langs", "eng+deu")

# Absolute path to the tesseract binary. Empty -> rely on PATH.
TESSERACT_CMD = os.getenv("tesseract_cmd", "")

# Hard cap on a single OCR call in seconds (pytesseract kills the subprocess).
OCR_TIMEOUT = int(os.getenv("ocr_timeout", "30"))
