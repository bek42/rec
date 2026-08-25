import rec.poller as poller


def _stub_render(monkeypatch):
    monkeypatch.setattr(poller, "render_html_to_pdf", lambda html: html.encode())


def test_image_attachment_alone_skips_body_pdf(monkeypatch):
    _stub_render(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="Taxi airport-hotel EUR 84.60",
        sender="Bharani Nitturi <bharani.nitturi@gmail.com>",
        date="Tue, 25 Aug 2026 09:06:13 +0200",
        html_body=None,
        text_body=None,
        attachments=[("receipt.jpg", "image/jpeg", b"fakejpegbytes")],
    )
    assert len(pdfs) == 1


def test_pdf_attachment_alone_skips_body_pdf(monkeypatch):
    _stub_render(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="Taxi receipt",
        sender="a@b.com",
        date="Tue, 25 Aug 2026 09:06:13 +0200",
        html_body=None,
        text_body=None,
        attachments=[("receipt.pdf", "application/pdf", b"%PDF-fake")],
    )
    assert len(pdfs) == 1
    assert pdfs[0][1] == b"%PDF-fake"


def test_no_attachments_renders_body(monkeypatch):
    _stub_render(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="Taxi receipt EUR 12.00",
        sender="a@b.com",
        date="Tue, 25 Aug 2026 09:06:13 +0200",
        html_body=None,
        text_body="paid 12 EUR",
        attachments=[],
    )
    assert len(pdfs) == 1


def test_image_and_pdf_attachments_both_render_without_body(monkeypatch):
    _stub_render(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="x",
        sender="a@b.com",
        date="Tue, 25 Aug 2026 09:06:13 +0200",
        html_body=None,
        text_body=None,
        attachments=[
            ("receipt.pdf", "application/pdf", b"%PDF-fake"),
            ("photo.jpg", "image/jpeg", b"fakejpegbytes"),
        ],
    )
    assert len(pdfs) == 2
