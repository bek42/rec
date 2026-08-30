import queue

import rec.pipeline.poller as poller
import rec.core.state as state


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
