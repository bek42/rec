import re
from email.utils import parseaddr, parsedate_to_datetime

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY"}
_CURRENCY_CODES = "GBP|USD|EUR|JPY|AUD|CAD|CHF|INR"

# Matches either "£12.99" / "$12" (symbol before amount) or "12.99 USD" / "12.99GBP"
# (amount before a 3-letter code) — the two most common receipt formats.
_AMOUNT_RE = re.compile(
    rf"(?:([£$€¥])\s?(\d+(?:[.,]\d{{2}})?))"
    rf"|(?:(\d+(?:[.,]\d{{2}})?)\s?({_CURRENCY_CODES}))"
)


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


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return cleaned or "unknown"


def _format_date(date_header: str) -> str:
    try:
        return parsedate_to_datetime(date_header).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "unknown-date"


def _format_sender(sender: str) -> str:
    display_name, email_addr = parseaddr(sender)
    label = display_name or (email_addr.split("@")[0] if email_addr else sender)
    return _sanitize(label)


def build_filename(
    subject: str,
    sender: str,
    date: str,
    text_body: str | None,
    html_body: str | None,
    index: int | None = None,
    total: int = 1,
) -> str:
    """[date]-[who the email is from]-[amount]-[currency].pdf, with an index
    suffix when an email produces more than one attachment."""
    amount, currency = extract_amount_and_currency(subject, text_body, html_body)
    base = "-".join(
        [
            _format_date(date),
            _format_sender(sender),
            _sanitize(amount) if amount else "unknown-amount",
            _sanitize(currency) if currency else "unknown-currency",
        ]
    )
    if total > 1 and index is not None:
        base = f"{base}-{index}"
    return f"{base}.pdf"
