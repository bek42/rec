"""llm_classify.py — optional OpenAI-based receipt categorization.

Tesseract/pypdf (ocr.py) already extract vendor/amount/currency reasonably
well via regex heuristics; what they can't do is understand what was actually
purchased — `classify_category` only pattern-matches a fixed keyword list, so
a line has to literally contain one of the listed words to resolve to
anything but "misc". When `OPENAI_ENABLED`, `classify_with_llm` reads the
OCR'd receipt text and asks a model to read the itemized line items the way a
human would; `build_filename` (filenames.py) prefers whichever of its
vendor/category/currency/amount fields come back non-empty over the regex
path, falling back field-by-field to the existing heuristics for the rest.

Every failure mode (disabled, no key, network, bad/unparseable response,
timeout) returns None so the caller degrades to those heuristics exactly as
it already does for an OCR failure — same philosophy as ocr_image/pdf_text
next door. This module never raises into the poll loop.
"""

import json
import urllib.error
import urllib.request

from ..core.config import OPENAI_API_KEY, OPENAI_ENABLED, OPENAI_MODEL, OPENAI_TIMEOUT, RECEIPT_CATEGORIES
from ..core.logging_setup import log

_API_URL = "https://api.openai.com/v1/chat/completions"

_SYSTEM_PROMPT = (
    "Extract data from OCR'd receipt text for an expense system. Look at the "
    "itemized line items (what was actually ordered/purchased), not just the "
    "business name, to decide the category — for example coffee/espresso/"
    "cappuccino/latte/flat white items mean the category is coffee, not meal. "
    "Respond with ONLY a JSON object, no other text, with these fields: "
    'vendor (short business name), category (pick the single best match from: '
    "{categories}), currency (ISO code like EUR, GBP, USD), amount (the total "
    "amount paid, as a plain decimal number, no currency symbol)."
)


def classify_with_llm(text: str) -> dict | None:
    """Best-effort OpenAI classification of OCR'd receipt text. Returns a dict
    with whichever of vendor/category/currency/amount the model supplied —
    the caller falls back to the regex heuristics for anything missing or
    None. Returns None outright when disabled, unconfigured, or the request
    fails in any way."""
    if not OPENAI_ENABLED:
        return None
    if not text or not text.strip():
        return None
    if not OPENAI_API_KEY:
        log.warning("llm_classify: openai_enabled=true but no API key configured - skipping")
        return None

    payload = json.dumps(
        {
            "model": OPENAI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT.format(categories=", ".join(RECEIPT_CATEGORIES)),
                },
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
    ).encode()

    req = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT) as resp:
            body = json.loads(resp.read())
        fields = json.loads(body["choices"][0]["message"]["content"])
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, OSError) as exc:
        log.warning("llm_classify: OpenAI request failed (%s) - falling back to OCR heuristics", exc)
        return None

    category = str(fields.get("category") or "").strip().lower()
    if category not in RECEIPT_CATEGORIES:
        category = None

    result = {
        "vendor": str(fields.get("vendor") or "").strip() or None,
        "category": category,
        "currency": str(fields.get("currency") or "").strip().upper() or None,
        "amount": str(fields["amount"]) if fields.get("amount") is not None else None,
    }
    if not any(result.values()):
        log.warning("llm_classify: OpenAI response had no usable fields - falling back")
        return None

    log.info("llm_classify: categorized via OpenAI (%s)", OPENAI_MODEL)
    return result
