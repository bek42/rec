import rec.pipeline.ocr as ocr
from rec.pipeline.ocr import (
    classify_category,
    extract_amount_and_currency,
    extract_vendor,
    ocr_image,
    pdf_text,
)


# --- classify_category -------------------------------------------------------


def test_classify_category_english():
    assert classify_category("Table 4 - Dinner\nMain course ... Dessert") == "meal"
    assert classify_category("Uber trip receipt - your ride fare") == "taxi"
    assert classify_category("National Rail single fare, off-peak") == "train"
    assert classify_category("Boarding pass - gate 22 - baggage") == "flight"
    assert classify_category("Seat reservation confirmation") == "seats"
    assert classify_category("Hotel booking - 2 night stay, city tax") == "hotel"
    assert classify_category("Unleaded petrol 40 litres, pump no 3") == "fuel"
    assert classify_category("Your American Express statement is ready") == "statement"


def test_classify_category_german():
    assert classify_category("Gaststätte - Mittagessen, Getränke") == "meal"
    assert classify_category("Taxifahrt Quittung - Fahrer") == "taxi"
    assert classify_category("Deutsche Bahn - Fahrkarte, Gleis 7") == "train"
    assert classify_category("Bordkarte - Abflug Flughafen München") == "flight"
    assert classify_category("Sitzplatzreservierung") == "seats"
    assert classify_category("Hotel - 2 Übernachtungen, Kurtaxe") == "hotel"
    assert classify_category("Tankstelle - Super E10, bleifrei") == "fuel"
    assert classify_category("Ihre Kreditkartenabrechnung") == "statement"


def test_classify_category_default_and_priority():
    assert classify_category("just some unrelated words here") == "misc"
    # "hotel" outranks "meal" when both keywords appear.
    assert classify_category("Hotel restaurant - breakfast included") == "hotel"


# --- extract_vendor --------------------------------------------------------


def test_extract_vendor_skips_noise_lines():
    text = "Kassenbon\nMusterstr. 5\n+49 89 1234567\nSTARBUCKS COFFEE\nTotal 4.99 EUR"
    assert extract_vendor(text) == "starbucks-coffee"


def test_extract_vendor_strips_legal_suffix():
    assert extract_vendor("REWE Markt GmbH\nHauptstr. 1") == "rewe-markt"


def test_extract_vendor_empty_when_nothing_usable():
    assert extract_vendor("") == ""
    assert extract_vendor("12.00\n99\n---") == ""


# --- extract_amount_and_currency -----------------------------------------


def test_amount_prefers_total_over_subtotal():
    text = "Subtotal 3.00\nService 0.50\nTotal £4.99"
    assert extract_amount_and_currency(text) == ("4.99", "GBP")


def test_amount_german_total_with_comma_decimal():
    text = "Zwischensumme 10,00\nMwSt 1,90\nGesamtbetrag 12,00 EUR"
    assert extract_amount_and_currency(text) == ("12,00", "EUR")


def test_amount_prefers_non_gbp_even_when_gbp_is_the_total():
    text = "Transaction 50.00 USD\nGBP equivalent £39.50\nTotal £39.50"
    assert extract_amount_and_currency(text) == ("50.00", "USD")


def test_amount_without_currency_token_is_treated_as_eur():
    assert extract_amount_and_currency("Betrag 50,00") == ("50,00", "EUR")


def test_amount_none_when_nothing_found():
    assert extract_amount_and_currency("no numbers worth mentioning") == (None, None)


def test_amount_ignores_date_fragments():
    # "25.08.2026" must not be read as an amount; the £ line wins.
    assert extract_amount_and_currency("Datum 25.08.2026\nTotal £8.40") == ("8.40", "GBP")


# --- ocr_image / pdf_text graceful degradation --------------------------


def test_ocr_image_returns_empty_on_unreadable_bytes():
    assert ocr_image(b"definitely not an image", "eng+deu") == ""


def test_ocr_image_returns_empty_when_dependency_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "pytesseract" or name == "PIL" or name.startswith("PIL."):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert ocr_image(b"whatever", "eng") == ""


def test_ocr_image_returns_empty_on_tesseract_error(monkeypatch):
    import pytesseract

    def _raise(*a, **k):
        raise RuntimeError("tesseract timeout")

    # A real 1x1 PNG so PIL.Image.open succeeds and image_to_string is reached.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c6360000002000154a24f2f0000000049454e44ae426082"
    )
    monkeypatch.setattr(pytesseract, "image_to_string", _raise)
    assert ocr_image(png, "eng") == ""


def test_pdf_text_returns_empty_on_broken_pdf():
    assert pdf_text(b"%PDF-1.7 totally broken") == ""
