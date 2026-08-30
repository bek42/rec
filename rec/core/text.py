"""Small shared text helpers used by both filenames.py and ocr.py.

These live in their own module so ocr.py can reuse them without importing
filenames.py (which imports ocr.py) — that would be a cycle.
"""

import re
from email.utils import parseaddr


def sanitize_slug(value: str) -> str:
    """Collapse anything that isn't ASCII alphanumeric into single hyphens."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return cleaned or "unknown"


def sender_slug(sender: str) -> str:
    """A filesystem-safe label for whoever an email is from: display name if
    present, else the address local-part, else the raw header."""
    display_name, email_addr = parseaddr(sender)
    label = display_name or (email_addr.split("@")[0] if email_addr else sender)
    return sanitize_slug(label)
