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
