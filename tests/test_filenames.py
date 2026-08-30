import re

from rec.pipeline.filenames import (
    build_filename,
    extract_amount_and_currency,
    format_amount_digits,
    short_id,
)

_ID = r"[a-z0-9]{5}"


# --- extract_amount_and_currency (email subject/body fallback, unchanged) ---


def test_extract_symbol_before_amount():
    assert extract_amount_and_currency("Your total is £4.99") == ("4.99", "GBP")


def test_extract_amount_before_code():
    assert extract_amount_and_currency("Charged 12.00 USD to your card") == ("12.00", "USD")


def test_extract_prefers_subject_over_body():
    amount, currency = extract_amount_and_currency("Total: $9.99", "Subtotal was £3.00, total £4.99")
    assert (amount, currency) == ("9.99", "USD")


def test_extract_returns_none_when_nothing_found():
    assert extract_amount_and_currency("Your order details", "no numbers here") == (None, None)


# --- format_amount_digits -------------------------------------------------


def test_format_amount_digits():
    assert format_amount_digits("495.86") == "49586"
    assert format_amount_digits("4.99") == "499"
    assert format_amount_digits("1.234,56") == "123456"
    assert format_amount_digits("12,00") == "1200"
    assert format_amount_digits("84.60") == "8460"
    assert format_amount_digits("90") == "9000"
    assert format_amount_digits(None) == "unknown"


# --- short_id ------------------------------------------------------------


def test_short_id_is_deterministic_and_shaped():
    assert re.fullmatch(_ID, short_id(b"receipt-bytes"))
    assert short_id(b"receipt-bytes") == short_id(b"receipt-bytes")
    assert short_id(b"a") != short_id(b"b")
    assert re.fullmatch(_ID, short_id("some-string-seed"))


# --- build_filename ----------------------------------------------------


def test_build_filename_from_ocr_text():
    name = build_filename(
        doc_text="STARBUCKS COFFEE\nTable 2\nTotal 4.99 EUR",
        subject="photo 2026-08-30",
        sender="macrodroid",
        text_body=None,
        html_body=None,
        seed=b"imagebytes",
    )
    assert re.fullmatch(rf"starbucks-coffee-meal-EUR-499-{_ID}\.pdf", name)


def test_build_filename_prefers_non_gbp_amount():
    name = build_filename(
        doc_text="AMERICAN EXPRESS\nTransaction 50.00 USD\nGBP amount £39.50\nTotal £39.50",
        subject="statement",
        sender="American Express <no-reply@amex.com>",
        text_body=None,
        html_body=None,
        seed=b"pdfbytes",
    )
    assert re.fullmatch(rf"american-express-statement-USD-5000-{_ID}\.pdf", name)


def test_build_filename_falls_back_to_sender_and_subject():
    name = build_filename(
        doc_text="",
        subject="Your trip total £4.99",
        sender="British Airways <no-reply@britishairways.com>",
        text_body=None,
        html_body=None,
        seed="seed",
    )
    assert re.fullmatch(rf"british-airways-flight-GBP-499-{_ID}\.pdf", name)


def test_build_filename_all_unknown():
    name = build_filename(
        doc_text="",
        subject="",
        sender="receipts@shop.com",
        text_body=None,
        html_body=None,
        seed="x",
    )
    assert re.fullmatch(rf"receipts-misc-unknown-unknown-{_ID}\.pdf", name)


def test_build_filename_appends_index_when_multiple():
    kwargs = dict(
        doc_text="",
        subject="x",
        sender="a@b.com",
        text_body=None,
        html_body=None,
        seed="s",
    )
    first = build_filename(**kwargs, index=1, total=2)
    second = build_filename(**kwargs, index=2, total=2)
    assert first.endswith("-1.pdf")
    assert second.endswith("-2.pdf")
    assert first != second
