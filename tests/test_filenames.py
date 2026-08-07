from rec.filenames import build_filename, extract_amount_and_currency


def test_extract_symbol_before_amount():
    assert extract_amount_and_currency("Your total is £4.99") == ("4.99", "GBP")


def test_extract_amount_before_code():
    assert extract_amount_and_currency("Charged 12.00 USD to your card") == ("12.00", "USD")


def test_extract_prefers_subject_over_body():
    amount, currency = extract_amount_and_currency("Total: $9.99", "Subtotal was £3.00, total £4.99")
    assert (amount, currency) == ("9.99", "USD")


def test_extract_falls_back_to_body_when_subject_has_no_amount():
    amount, currency = extract_amount_and_currency("Your order details", "Total £ 4.99 paid today")
    assert (amount, currency) == ("4.99", "GBP")


def test_extract_returns_none_when_nothing_found():
    assert extract_amount_and_currency("Your order details", "no numbers here") == (None, None)


def test_build_filename_full_format():
    name = build_filename(
        subject="Your order details",
        sender="British Airways <no-reply@britishairways.com>",
        date="Thu, 06 Aug 2026 16:54:00 +0000",
        text_body="Total £ 4.99",
        html_body=None,
    )
    assert name == "2026-08-06-British-Airways-4-99-GBP.pdf"


def test_build_filename_falls_back_on_missing_amount():
    name = build_filename(
        subject="Your order details",
        sender="British Airways <no-reply@britishairways.com>",
        date="Thu, 06 Aug 2026 16:54:00 +0000",
        text_body="no amount mentioned here",
        html_body=None,
    )
    assert name == "2026-08-06-British-Airways-unknown-amount-unknown-currency.pdf"


def test_build_filename_falls_back_on_unparseable_date():
    name = build_filename(
        subject="x",
        sender="a@b.com",
        date="not a date",
        text_body=None,
        html_body=None,
    )
    assert name.startswith("unknown-date-")


def test_build_filename_uses_email_local_part_when_no_display_name():
    name = build_filename(
        subject="x",
        sender="receipts@shop.com",
        date="Thu, 06 Aug 2026 16:54:00 +0000",
        text_body=None,
        html_body=None,
    )
    assert "receipts" in name


def test_build_filename_appends_index_when_multiple():
    kwargs = dict(
        subject="x",
        sender="a@b.com",
        date="Thu, 06 Aug 2026 16:54:00 +0000",
        text_body=None,
        html_body=None,
    )
    first = build_filename(**kwargs, index=1, total=2)
    second = build_filename(**kwargs, index=2, total=2)
    assert first.endswith("-1.pdf")
    assert second.endswith("-2.pdf")
    assert first != second
