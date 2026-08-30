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
HTTP_MAX_UPLOAD_BYTES = int(os.getenv("http_max_upload_bytes", str(25 * 1024 * 1024)))
# How long the handler waits for the poll-loop thread to render + send before
# returning 504 (the upload still completes server-side).
HTTP_RESULT_TIMEOUT = int(os.getenv("http_result_timeout", "60"))

# Bearer token for "POST /upload" — a SECRET NAME looked up in Infisical (same
# indirection as the Gmail creds), not the value itself. Defaults to reusing
# the Gmail Infisical section.
key_http_infisical_section = os.getenv("key_http_infisical_section") or key_gmail_infisical_section
key_http_token = os.getenv("key_http_token", "rec-http-token")

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
