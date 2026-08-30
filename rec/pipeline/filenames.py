import hashlib
import re

from ..core.text import sender_slug
from .ocr import classify_category, extract_vendor
from .ocr import extract_amount_and_currency as ocr_amount_and_currency

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY"}
_CURRENCY_CODES = "GBP|USD|EUR|JPY|AUD|CAD|CHF|INR"

# Matches either "£12.99" / "$12" (symbol before amount) or "12.99 USD" / "12.99GBP"
# (amount before a 3-letter code) — the two most common receipt formats.
_AMOUNT_RE = re.compile(
    rf"(?:([£$€¥])\s?(\d+(?:[.,]\d{{2}})?))"
    rf"|(?:(\d+(?:[.,]\d{{2}})?)\s?({_CURRENCY_CODES}))"
)

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def extract_amount_and_currency(*texts: str | None) -> tuple[str | None, str | None]:
    """Best-effort extraction of a monetary amount + currency from email text.
    Checks each text in order (caller should pass subject before body — the
    subject is shorter and more likely to state the total cleanly) and returns
    the first match. Returns (None, None) if nothing looks like an amount."""
    for text in texts:
        if not text:
            continue
        match = _AMOUNT_RE.search(text)
        if not match:
            continue
        if match.group(1):
            symbol, amount = match.group(1), match.group(2)
            currency = _CURRENCY_SYMBOLS.get(symbol, symbol)
        else:
            amount, currency = match.group(3), match.group(4)
        return amount.replace(",", ""), currency
    return None, None


def format_amount_digits(amount: str | None) -> str:
    """Digits only, with the last two digits always the minor unit (cents/pence).
    '495.86'->'49586', '4.99'->'499', '1.234,56'->'123456', '12,00'->'1200',
    '90'->'9000' (no decimal seen -> whole units). None -> 'unknown'."""
    if not amount:
        return "unknown"
    m = re.search(r"[.,](\d{1,2})\s*$", amount)
    if m:
        frac = m.group(1).ljust(2, "0")
        whole = re.sub(r"\D", "", amount[: m.start()])
    else:
        frac = "00"
        whole = re.sub(r"\D", "", amount)
    return (whole + frac).lstrip("0") or "0"


def short_id(seed: bytes | str, n: int = 5) -> str:
    """A deterministic n-char [a-z0-9] id derived from `seed`. Feeding the same
    receipt bytes always yields the same id, so a retry can't produce a
    differently-named duplicate."""
    raw = seed.encode("utf-8", "replace") if isinstance(seed, str) else seed
    num = int.from_bytes(hashlib.sha1(raw).digest()[:8], "big")
    out = []
    for _ in range(n):
        num, rem = divmod(num, len(_ID_ALPHABET))
        out.append(_ID_ALPHABET[rem])
    return "".join(out)


def build_filename(
    doc_text: str | None,
    subject: str,
    sender: str,
    text_body: str | None,
    html_body: str | None,
    seed: bytes | str,
    index: int | None = None,
    total: int = 1,
) -> str:
    """vendor-category-CUR-amount-id.pdf

    `doc_text` is the OCR output (images) or extracted text layer (PDF
    attachments); when present it drives every field. Otherwise the fields come
    from the email sender + subject/body regex. An index suffix is added when one
    source produces more than one attachment."""
    scrape_texts = [t for t in (doc_text, subject, text_body, html_body) if t]

    vendor = (extract_vendor(doc_text) if doc_text else "") or sender_slug(sender) or "unknown"
    category = classify_category(" ".join([*scrape_texts, sender or ""]))
    amount, currency = ocr_amount_and_currency(*scrape_texts)
    if not amount:
        amount, currency = extract_amount_and_currency(subject, text_body, html_body)

    base = "-".join(
        [
            vendor.lower(),
            category,
            currency or "unknown",
            format_amount_digits(amount) if amount else "unknown",
            short_id(seed),
        ]
    )
    if total > 1 and index is not None:
        base = f"{base}-{index}"
    return f"{base}.pdf"
