"""OCR + PDF-text extraction and the heuristics that turn recognised receipt
text into the parts of an output filename (vendor / category / currency /
amount).

`ocr_image` and `pdf_text` do the I/O and are best-effort: every failure mode
(missing dependency, missing tesseract binary, missing language data, an
unreadable image, a text-layer-less PDF, a subprocess timeout) returns "" so the
caller falls back to the sender + subject/body regex. The rest of the module is
pure string work and is unit-tested with literal inputs.
"""

import io
import re
from collections import Counter

from ..core.config import OCR_TIMEOUT, TESSERACT_CMD
from ..core.logging_setup import log
from ..core.text import sanitize_slug

# ---------------------------------------------------------------------------
# I/O — image bytes / PDF bytes -> plain text (or "" on any failure)
# ---------------------------------------------------------------------------


def ocr_image(data: bytes, langs: str) -> str:
    """Run Tesseract over in-memory image bytes. `langs` is a '+'-joined list of
    Tesseract language codes (e.g. "eng+deu"). Returns "" on any failure."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        log.warning("ocr: pytesseract/Pillow unavailable - skipping OCR")
        return ""

    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            text = pytesseract.image_to_string(img, lang=langs, timeout=OCR_TIMEOUT)
        return text.strip()
    except Exception as exc:
        log.warning("ocr: OCR failed (%s) - falling back to text heuristics", exc)
        return ""


def pdf_text(data: bytes) -> str:
    """Extract the embedded text layer of a PDF. Returns "" when the PDF has no
    text layer (a scan) or anything goes wrong."""
    try:
        from pypdf import PdfReader
    except Exception:
        log.warning("ocr: pypdf unavailable - skipping PDF text extraction")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        log.warning("ocr: PDF text extraction failed (%s)", exc)
        return ""


# ---------------------------------------------------------------------------
# Category — ordered whole-word / phrase match, first hit wins, "misc" default
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "statement",
        (
            "statement", "account summary", "closing balance", "opening balance",
            "minimum payment", "credit card statement", "kontoauszug",
            "kreditkartenabrechnung", "rechnungsabschluss", "american express", "amex",
            "lloyds", "barclaycard", "monzo", "starling",
        ),
    ),
    (
        "flight",
        (
            "flight", "airline", "airways", "boarding", "boarding pass", "e-ticket",
            "baggage", "pnr", "airport", "airfare", "flug", "flugticket", "bordkarte",
            "gepäck", "abflug", "flughafen", "lufthansa", "ryanair", "easyjet",
            "eurowings", "british airways", "klm", "wizz air", "condor",
        ),
    ),
    (
        "train",
        (
            "train", "rail", "railway", "railcard", "off-peak", "national rail",
            "trainline", "eurostar", "bahn", "zug", "fahrkarte", "fahrschein",
            "bahncard", "gleis", "hauptbahnhof", "deutsche bahn", "sncf", "tgv",
            "öbb", "sbb",
        ),
    ),
    (
        "taxi",
        (
            "taxi", "cab", "minicab", "private hire", "uber", "bolt", "free now",
            "freenow", "lyft", "grab", "taxifahrt", "mietwagen", "funktaxi",
        ),
    ),
    (
        "hotel",
        (
            "hotel", "hostel", "motel", "guest house", "room rate", "room charge",
            "night stay", "check-in", "check-out", "city tax", "resort fee",
            "booking.com", "expedia", "marriott", "hilton", "ibis", "novotel",
            "premier inn", "travelodge", "motel one", "übernachtung", "zimmer",
            "gästehaus", "pension", "unterkunft", "kurtaxe", "anreise", "abreise",
        ),
    ),
    (
        "fuel",
        (
            "petrol", "diesel", "unleaded", "gasoline", "litres", "liters",
            "filling station", "pump no", "octane", "adblue", "shell", "esso",
            "aral", "totalenergies", "kraftstoff", "benzin", "super e10", "super e5",
            "tankstelle", "tanken", "zapfsäule", "bleifrei",
        ),
    ),
    (
        "seats",
        (
            "seat reservation", "reservation fee", "reserved seat",
            "sitzplatzreservierung", "sitzplatz", "platzreservierung",
            "reservierungsentgelt",
        ),
    ),
    (
        "meal",
        (
            "restaurant", "cafe", "café", "bistro", "brasserie", "coffee", "espresso",
            "cappuccino", "latte", "lunch", "dinner", "breakfast", "brunch", "menu",
            "starter", "main course", "dessert", "cover charge", "service charge",
            "gratuity", "takeaway", "starbucks", "costa coffee", "pret a manger",
            "mcdonald", "burger king", "kfc", "nando", "wagamama", "greggs",
            "five guys", "gaststätte", "gasthaus", "speisen", "getränke",
            "mittagessen", "abendessen", "frühstück", "trinkgeld", "bewirtung",
            "imbiss", "bäckerei", "konditorei", "kaffee",
        ),
    ),
]


def classify_category(text: str) -> str:
    lowered = (text or "").lower()
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", lowered):
                return category
    return "misc"


# ---------------------------------------------------------------------------
# Vendor — the merchant name printed at the top of a receipt
# ---------------------------------------------------------------------------

_VENDOR_NOISE_RE = re.compile(r"https?://|www\.|@|\+?\d[\d ()/-]{6,}")
_VENDOR_DATE_RE = re.compile(r"^\d{1,4}[.\-/]\d{1,2}(?:[.\-/]\d{1,4})?(?:\s+\d{1,2}:\d{2})?$")
# Street-address lines ("Musterstr. 5", "12 High Street") are not the vendor.
_VENDOR_ADDRESS_RE = re.compile(
    r"str(?:\.|aße|asse)\b|\bstreet\b|\broad\b|\bavenue\b|\blane\b|\bweg\b"
    r"|\bplatz\b|\ballee\b|\bgasse\b|\d{1,5}\s*$",
    re.IGNORECASE,
)
_DOC_TYPE_WORDS = {
    "receipt", "invoice", "bill", "quittung", "rechnung", "beleg", "kassenbon",
    "bon", "kassenzettel",
}
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:gmbh(?:\s*&\s*co\.?\s*kg)?|ag|kg|ohg|mbh|e\.?\s?k\.?|ltd\.?|limited|plc"
    r"|inc\.?|llc|s\.r\.l\.?|s\.a\.?|b\.v\.?)\.?\s*$",
    re.IGNORECASE,
)


def extract_vendor(text: str) -> str:
    """Best-effort merchant slug from the first few lines. Returns "" when
    nothing on those lines looks like a name."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    for line in lines[:6]:
        alpha = sum(c.isalpha() for c in line)
        if alpha < 3:
            continue
        noise = sum(1 for c in line if not c.isalpha() and not c.isspace())
        if noise / len(line) > 0.6:
            continue
        if _VENDOR_NOISE_RE.search(line):
            continue
        if _VENDOR_DATE_RE.match(line):
            continue
        if _VENDOR_ADDRESS_RE.search(line):
            continue
        if line.lower().strip(":.-* ") in _DOC_TYPE_WORDS:
            continue
        cleaned = _LEGAL_SUFFIX_RE.sub("", line).strip(" ,.-*")
        words = cleaned.split()
        if not words:
            continue
        slug = sanitize_slug(" ".join(words[:4])[:40]).lower()
        if slug and slug != "unknown":
            return slug
    return ""


# ---------------------------------------------------------------------------
# Amount + currency — scored candidates, non-GBP amount preferred
# ---------------------------------------------------------------------------

_SYMBOL_TO_CODE = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY", "₹": "INR"}
_CODE_RE = re.compile(
    r"\b(GBP|USD|EUR|JPY|AUD|CAD|CHF|INR|SEK|NOK|DKK|PLN|CZK)\b", re.IGNORECASE
)
# "1.234,56" / "1,234.56" / "12,00" / "4.99" / bare "90"
_MONEY_RE = re.compile(r"\d{1,3}(?:[.\s]\d{3})+[.,]\d{1,2}|\d+[.,]\d{1,2}|\d+")

_TOTAL_KW = (
    "grand total", "total", "amount due", "amount paid", "balance due", "to pay",
    "gesamtbetrag", "gesamtsumme", "gesamt", "summe", "rechnungsbetrag",
    "zu zahlen", "zahlbetrag", "endbetrag", "bruttobetrag",
)
_EXCLUDE_KW = (
    "subtotal", "sub-total", "zwischensumme", "netto", "net amount", "vat", "mwst",
    "ust", "tax", "steuer", "change due", "rückgeld", "trinkgeld", "pfand", "deposit",
)


def _amount_to_float(raw: str) -> float:
    m = re.search(r"[.,](\d{1,2})\s*$", raw)
    if m:
        frac = m.group(1).ljust(2, "0")
        whole = re.sub(r"\D", "", raw[: m.start()]) or "0"
    else:
        frac = "00"
        whole = re.sub(r"\D", "", raw) or "0"
    return int(whole) + int(frac) / 100


def _line_currency(line: str) -> str | None:
    m = _CODE_RE.search(line)
    if m:
        return m.group(1).upper()
    for sym, code in _SYMBOL_TO_CODE.items():
        if sym in line:
            return code
    return None


def _candidates(text: str) -> list[tuple[float, str | None, str]]:
    """(score, currency_code_or_None, raw_amount) for every plausible money
    mention in `text`. Higher score = more likely to be the document total."""
    out: list[tuple[float, str | None, str]] = []
    for idx, line in enumerate(text.splitlines()):
        low = line.lower()
        has_total = any(k in low for k in _TOTAL_KW)
        has_excl = any(k in low for k in _EXCLUDE_KW)
        code = _line_currency(line)
        for mm in _MONEY_RE.finditer(line):
            raw = mm.group(0)
            # Skip date / version fragments like "25.08.2026": a money match
            # flanked by a further separator+digit is not an amount.
            after = line[mm.end() : mm.end() + 2]
            before = line[max(0, mm.start() - 2) : mm.start()]
            if re.match(r"[.,/\-]\d", after) or re.search(r"\d[.,/\-]$", before):
                continue
            is_decimal = bool(re.search(r"[.,]\d{1,2}$", raw))
            if not is_decimal and not (code or has_total):
                continue
            val = _amount_to_float(raw)
            if val <= 0:
                continue
            score = float(idx) + min(val, 100.0) / 100.0
            if has_total:
                score += 100.0
            if has_excl:
                score -= 100.0
            out.append((score, code, raw))
    return out


def extract_amount_and_currency(*texts: str | None) -> tuple[str | None, str | None]:
    """Pick the document total across all given texts. A non-GBP amount always
    wins over a GBP one (foreign receipts, Amex/Lloyds statements); an amount
    with no resolvable currency is treated as EUR. Returns (raw_amount, code) or
    (None, None) when no amount is found."""
    cands: list[tuple[float, str | None, str]] = []
    for text in texts:
        if text:
            cands.extend(_candidates(text))
    if not cands:
        return None, None

    doc_codes = [c for _, c, _ in cands if c]
    fallback = Counter(doc_codes).most_common(1)[0][0] if doc_codes else None
    resolved = [(score, code or fallback, raw) for score, code, raw in cands]

    non_gbp = [c for c in resolved if c[1] and c[1] != "GBP"]
    if non_gbp:
        _, code, raw = max(non_gbp, key=lambda c: c[0])
        return raw, code

    gbp = [c for c in resolved if c[1] == "GBP"]
    if gbp:
        _, _, raw = max(gbp, key=lambda c: c[0])
        return raw, "GBP"

    # An amount, but nothing anywhere says which currency -> treat as non-GBP.
    _, _, raw = max(resolved, key=lambda c: c[0])
    return raw, "EUR"
