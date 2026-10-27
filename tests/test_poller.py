import base64
import queue

import rec.pipeline.poller as poller
import rec.core.state as state

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _stub_render(monkeypatch):
    monkeypatch.setattr(poller, "render_html_to_pdf", lambda html: html.encode())


def _stub_ocr(monkeypatch, text=""):
    monkeypatch.setattr(poller, "ocr_image", lambda data, langs: text)
    monkeypatch.setattr(poller, "pdf_text", lambda data: text)


def test_image_attachment_alone_skips_body_pdf(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="Taxi airport-hotel EUR 84.60",
        sender="Bharani Nitturi <bharani.nitturi@gmail.com>",
        date="Tue, 25 Aug 2026 09:06:13 +0200",
        html_body=None,
        text_body=None,
        attachments=[("receipt.jpg", "image/jpeg", b"fakejpegbytes")],
    )
    assert len(pdfs) == 1


def test_octet_stream_jpeg_sniffed_as_image(monkeypatch):
    # Some senders (and Gmail's own forward-of-a-camera-upload) attach a photo
    # as application/octet-stream instead of image/jpeg. Regression test for
    # the bug where this silently degraded to a near-empty email-body PDF.
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    pdfs = poller.normalize_to_pdfs(
        subject="[rec] {v=Receipt Type}",
        sender="Bharani Nitturi <bharani.nitturi@gmail.com>",
        date="Mon, 19 Oct 2026 13:28:14 -0400",
        html_body=None,
        text_body=None,
        attachments=[("20261019_175700.jpg", "application/octet-stream", jpeg_bytes)],
    )
    assert len(pdfs) == 1
    # Rendered from the photo (base64 embedded in the stubbed <img> HTML),
    # not from the near-empty email body.
    assert base64.b64encode(jpeg_bytes).decode() in pdfs[0][1].decode()


def test_octet_stream_non_image_still_skipped(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="Some receipt",
        sender="Bharani Nitturi <bharani.nitturi@gmail.com>",
        date="Mon, 19 Oct 2026 13:28:14 -0400",
        html_body=None,
        text_body="total EUR 12.00",
        attachments=[("statement.docx", "application/octet-stream", b"not actually an image")],
    )
    # No image/PDF survives sniffing -> falls back to rendering the body, as before.
    assert len(pdfs) == 1


def test_image_with_substantial_body_renders_both(monkeypatch):
    # Booking confirmations (Capital Cars and similar) put the actual receipt
    # - booking ref, pickup/destination, driver, fare - in the HTML body and
    # attach only an incidental image (a route map) alongside it. Regression
    # test for the bug where fixing octet-stream sniffing on that same image
    # caused the real content (the body) to be dropped entirely, leaving only
    # a near-blank PDF of the map.
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    booking_html = (
        "<table><tr><td>Booking Reference</td><td>65935674A</td></tr>"
        "<tr><td>Pickup</td><td>Heathrow Terminal 5</td></tr>"
        "<tr><td>Destination</td><td>66 Rosehill Park, Reading</td></tr>"
        "<tr><td>Driver Number</td><td>70</td></tr></table>"
    )
    pdfs = poller.normalize_to_pdfs(
        subject="Thank you for booking with Capital Cars",
        sender="Capital Cars <noreply@capitalcars.example>",
        date="Thu, 22 Oct 2026 18:37:00 +0100",
        html_body=booking_html,
        text_body=None,
        attachments=[("png_284_BOOKING_RECEIPT_66230180.png", "application/octet-stream", _PNG)],
    )
    assert len(pdfs) == 2
    rendered = [pdf_bytes.decode() for _, pdf_bytes in pdfs]
    assert any("Booking Reference" in r for r in rendered)  # the body PDF
    assert any(base64.b64encode(_PNG).decode() in r for r in rendered)  # the map PDF


def test_image_with_trivial_body_skips_body_pdf(monkeypatch):
    # Opposite case, must not regress: a photographed receipt with an empty
    # body should still produce only the image PDF, not also a near-blank
    # "email body" PDF.
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    pdfs = poller.normalize_to_pdfs(
        subject="[rec] {v=Receipt Type}",
        sender="Bharani Nitturi <bharani.nitturi@gmail.com>",
        date="Mon, 19 Oct 2026 13:28:14 -0400",
        html_body="",
        text_body=None,
        attachments=[("20261019_175700.jpg", "image/jpeg", _PNG)],
    )
    assert len(pdfs) == 1


def test_llm_classify_result_drives_filename(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch, "2x Flat White 6,60\nGESAMT 8,60")
    monkeypatch.setattr(
        poller,
        "classify_with_llm",
        lambda text: {"vendor": "MINT42", "category": "coffee", "currency": "EUR", "amount": "8.60"},
    )
    pdfs = poller.normalize_to_pdfs(
        subject="receipt",
        sender="receipts@shop.com",
        date="",
        html_body=None,
        text_body=None,
        attachments=[("receipt.jpg", "image/jpeg", b"fakejpegbytes")],
    )
    assert len(pdfs) == 1
    assert pdfs[0][0].startswith("mint42-coffee-EUR-860-")


def test_llm_classify_not_called_for_body_only_output(monkeypatch):
    # No image/PDF attachment -> doc_text is "" for the rendered-body output,
    # so classify_with_llm (which has nothing itemized to read) must not run.
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)

    def _boom(text):
        raise AssertionError("classify_with_llm should not be called without doc_text")

    monkeypatch.setattr(poller, "classify_with_llm", _boom)
    pdfs = poller.normalize_to_pdfs(
        subject="Taxi receipt EUR 12.00",
        sender="a@b.com",
        date="Tue, 25 Aug 2026 09:06:13 +0200",
        html_body=None,
        text_body="paid 12 EUR",
        attachments=[],
    )
    assert len(pdfs) == 1


def test_pdf_attachment_alone_skips_body_pdf(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
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
    _stub_ocr(monkeypatch)
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
    _stub_ocr(monkeypatch)
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


def test_image_ocr_drives_filename(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch, "STARBUCKS COFFEE\nTable 2\nTotal 4.99 EUR")
    pdfs = poller.normalize_to_pdfs(
        subject="photo 2026-08-30",
        sender="macrodroid",
        date="",
        html_body=None,
        text_body=None,
        attachments=[("shot.jpg", "image/jpeg", b"fakejpegbytes")],
    )
    assert len(pdfs) == 1
    assert pdfs[0][0].startswith("starbucks-coffee-meal-EUR-499-")


def test_image_ocr_empty_falls_back_to_subject(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch, "")
    pdfs = poller.normalize_to_pdfs(
        subject="Costa 4.75 GBP",
        sender="macrodroid",
        date="",
        html_body=None,
        text_body=None,
        attachments=[("shot.jpg", "image/jpeg", b"fakejpegbytes")],
    )
    assert "-GBP-475-" in pdfs[0][0]


def test_pdf_text_drives_filename_with_non_gbp_preference(monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(
        monkeypatch,
        "AMERICAN EXPRESS\nTransaction 50.00 USD\nGBP amount £39.50\nTotal £39.50",
    )
    pdfs = poller.normalize_to_pdfs(
        subject="statement",
        sender="American Express <no-reply@amex.com>",
        date="",
        html_body=None,
        text_body=None,
        attachments=[("stmt.pdf", "application/pdf", b"%PDF-fake")],
    )
    assert pdfs[0][0].startswith("american-express-statement-USD-5000-")
    assert pdfs[0][1] == b"%PDF-fake"


def _make_upload(image_bytes=b"fakejpegbytes"):
    return poller.HttpUpload(
        subject="Costa 4.75 GBP",
        sender="macrodroid",
        date="Tue, 25 Aug 2026 09:06:13 +0000",
        attachments=[("shot.jpg", "image/jpeg", image_bytes)],
        result_q=queue.Queue(),
    )


def test_forward_upload_sends_and_dedupes(tmp_path, monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    monkeypatch.setattr(poller, "get_gmail_credentials", lambda: ("u@example.com", "pw"))
    monkeypatch.setattr(state, "DEDUP_STATE_PATH", str(tmp_path / "dedup.json"))
    sent = []
    monkeypatch.setattr(
        poller,
        "send_with_attachments",
        lambda user, pw, to, subj, body, pdfs: sent.append((subj, [f for f, _ in pdfs])),
    )

    job = _make_upload()
    files = poller.forward_upload(job, state.load_state())
    assert len(files) == 1
    assert len(sent) == 1
    assert sent[0][0] == "[rec] Costa 4.75 GBP"

    # Identical bytes on a retry -> deduped, no second send.
    assert poller.forward_upload(_make_upload(), state.load_state()) == []
    assert len(sent) == 1


def test_drain_http_queue_reports_outcome(tmp_path, monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    monkeypatch.setattr(poller, "get_gmail_credentials", lambda: ("u@example.com", "pw"))
    monkeypatch.setattr(state, "DEDUP_STATE_PATH", str(tmp_path / "dedup.json"))
    monkeypatch.setattr(poller, "send_with_attachments", lambda *a, **k: None)

    job_q = queue.Queue()
    job = _make_upload()
    job_q.put(job)
    poller._drain_http_queue(job_q)

    outcome, detail = job.result_q.get_nowait()
    assert outcome == "ok"
    assert len(detail) == 1
    assert job_q.empty()


def test_drain_http_queue_reports_error(tmp_path, monkeypatch):
    _stub_render(monkeypatch)
    _stub_ocr(monkeypatch)
    monkeypatch.setattr(poller, "get_gmail_credentials", lambda: ("u@example.com", "pw"))
    monkeypatch.setattr(state, "DEDUP_STATE_PATH", str(tmp_path / "dedup.json"))

    def _boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(poller, "send_with_attachments", _boom)

    job_q = queue.Queue()
    job = _make_upload()
    job_q.put(job)
    poller._drain_http_queue(job_q)

    outcome, detail = job.result_q.get_nowait()
    assert outcome == "error"
    assert "smtp down" in detail
