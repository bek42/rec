import base64
import hashlib
import queue
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    DEST_EMAIL,
    GMAIL_LABEL_IN,
    GMAIL_LABEL_OUT,
    HEARTBEAT_PATH,
    HTTP_ENABLED,
    POLL_SECONDS,
    SUBJECT_TRIGGER,
    TEST_MODE,
)
from .filenames import build_filename
from .forwarder import send_with_attachments
from .http_server import HttpUpload, build_server
from .imap_watcher import (
    connect,
    extract_body_and_attachments,
    fetch_gm_msgid,
    fetch_message,
    list_candidate_uids,
    move_to_out_label,
)
from .logging_setup import log
from .pdf import close_browser, render_html_to_pdf, wrap_email_as_html
from .secrets import get_gmail_credentials
from .state import already_forwarded, load_state, mark_forwarded, save_state

_IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp"}


def normalize_to_pdfs(
    subject: str,
    sender: str,
    date: str,
    html_body: str | None,
    text_body: str | None,
    attachments: list[tuple[str, str, bytes]],
) -> list[tuple[str, bytes]]:
    """PDF attachments pass through unchanged. Image attachments (photographed
    receipts) are individually wrapped into a minimal <img> HTML page and
    rendered to PDF. The email body is only rendered to its own PDF when
    there's no PDF or image attachment to carry the receipt instead —
    otherwise a photographed receipt would produce a near-empty "email body"
    PDF alongside the real one. Anything else (docx/xlsx/zip/...) is logged
    and skipped — Playwright renders HTML, it does not convert arbitrary
    office formats. All outputs are named [date]-[sender]-[amount]-[currency].pdf
    regardless of source, so a PDF attachment forwarded as-is gets the same
    naming as a rendered body."""
    pdf_bytes_list: list[bytes] = []
    has_pdf = any(ct == "application/pdf" for _, ct, _ in attachments)
    has_image = any(ct in _IMAGE_TYPES for _, ct, _ in attachments)

    if has_pdf:
        pdf_bytes_list.extend(data for _, ct, data in attachments if ct == "application/pdf")
    elif not has_image:
        html = wrap_email_as_html(subject, sender, date, html_body, text_body)
        pdf_bytes_list.append(render_html_to_pdf(html))

    for fn, ct, data in attachments:
        if ct in _IMAGE_TYPES:
            b64 = base64.b64encode(data).decode()
            img_html = (
                f'<html><body style="margin:0"><img src="data:{ct};base64,{b64}" '
                'style="max-width:100%"></body></html>'
            )
            pdf_bytes_list.append(render_html_to_pdf(img_html))
        elif ct != "application/pdf":
            log.warning(
                "poller: cannot normalize '%s' (%s) to PDF - forwarding as-is not implemented, skipping",
                fn,
                ct,
            )

    total = len(pdf_bytes_list)
    return [
        (build_filename(subject, sender, date, text_body, html_body, index=i + 1, total=total), data)
        for i, data in enumerate(pdf_bytes_list)
    ]


def process_once() -> None:
    username, app_password = get_gmail_credentials()
    state = load_state()
    imap = connect(username, app_password)
    try:
        for uid in list_candidate_uids(imap):
            gm_msgid = fetch_gm_msgid(imap, uid)
            if not gm_msgid or already_forwarded(state, gm_msgid):
                continue

            msg = fetch_message(imap, uid)
            if msg is None:
                continue

            subject = msg.get("Subject", "(no subject)")
            sender = msg.get("From", "(unknown sender)")
            date = msg.get("Date", "")
            html_body, text_body, attachments = extract_body_and_attachments(msg)
            pdfs = normalize_to_pdfs(subject, sender, date, html_body, text_body, attachments)

            body = (
                f"Forwarded by rec from Gmail label '{GMAIL_LABEL_IN}'.\n"
                f"Original From: {sender}\nOriginal Date: {date}\nOriginal Subject: {subject}\n"
            )
            send_with_attachments(
                username, app_password, DEST_EMAIL, f"{SUBJECT_TRIGGER} {subject}", body, pdfs
            )

            mark_forwarded(state, gm_msgid, subject, datetime.now(timezone.utc).isoformat())
            save_state(state)
            move_to_out_label(imap, uid)
    finally:
        imap.logout()


def forward_upload(job: HttpUpload, state: dict) -> list[str]:
    """Run one HTTP-submitted image through the same normalize + forward path as
    an emailed attachment. Deduplicated on the image bytes so a client retry
    can't double-send. Must run on the poll-loop thread — Playwright's sync API
    is bound to whichever thread started Chromium."""
    digest = hashlib.sha256(b"".join(data for _, _, data in job.attachments)).hexdigest()
    key = f"http:{digest}"
    if already_forwarded(state, key):
        log.info("poller: HTTP upload %s already forwarded - skipping", key)
        return []

    username, app_password = get_gmail_credentials()
    pdfs = normalize_to_pdfs(job.subject, job.sender, job.date, None, None, job.attachments)
    body = f"Forwarded by rec (HTTP upload from {job.sender}).\nSubject: {job.subject}\n"
    send_with_attachments(
        username, app_password, DEST_EMAIL, f"{SUBJECT_TRIGGER} {job.subject}", body, pdfs
    )

    mark_forwarded(state, key, job.subject, datetime.now(timezone.utc).isoformat())
    save_state(state)
    filenames = [fn for fn, _ in pdfs]
    log.info("poller: forwarded HTTP upload %s (%d file(s))", key, len(filenames))
    return filenames


def _drain_http_queue(job_q: "queue.Queue[HttpUpload]") -> None:
    """Process every pending upload, reporting the outcome back to each waiting
    request handler. One bad upload never aborts the drain or the poll loop."""
    while True:
        try:
            job = job_q.get_nowait()
        except queue.Empty:
            return
        try:
            files = forward_upload(job, load_state())
            job.result_q.put(("ok", files))
        except Exception as exc:
            log.exception("poller: error forwarding HTTP upload")
            job.result_q.put(("error", str(exc)))


def _touch_heartbeat() -> None:
    path = Path(HEARTBEAT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def run() -> None:
    log.info(
        "rec: watcher started - watching label '%s' and inbox subjects containing '%s' "
        "(forwarded mail moves to '%s'), polling every %ss (test_mode=%s)",
        GMAIL_LABEL_IN,
        SUBJECT_TRIGGER,
        GMAIL_LABEL_OUT,
        POLL_SECONDS,
        TEST_MODE,
    )
    job_q: "queue.Queue[HttpUpload] | None" = None
    server = None
    if HTTP_ENABLED:
        try:
            job_q = queue.Queue()
            server = build_server(job_q)
            threading.Thread(target=server.serve_forever, name="rec-http", daemon=True).start()
        except Exception:
            # A broken HTTP config must never take down the email poll loop, and
            # must not crash-loop the container past CI's health gate.
            log.exception("rec: HTTP upload channel failed to start - continuing email-only")
            job_q = None
            server = None

    def _shutdown(*_):
        if server is not None:
            server.shutdown()
        close_browser()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        if job_q is not None:
            _drain_http_queue(job_q)

        try:
            process_once()
        except Exception:
            log.exception("rec: unhandled error during poll cycle")

        if job_q is not None:
            _drain_http_queue(job_q)

        _touch_heartbeat()

        if TEST_MODE:
            log.info("rec: TEST_MODE=true - exiting after single poll cycle")
            break

        if job_q is not None:
            # Wake as soon as an upload lands; otherwise fall through after the
            # normal interval. Put the job back for _drain_http_queue at the top
            # of the next iteration.
            try:
                job_q.put(job_q.get(timeout=POLL_SECONDS))
            except queue.Empty:
                pass
        else:
            time.sleep(POLL_SECONDS)

    close_browser()
