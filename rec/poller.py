import base64
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import DEST_EMAIL, GMAIL_LABEL_IN, GMAIL_LABEL_OUT, HEARTBEAT_PATH, POLL_SECONDS, TEST_MODE
from .filenames import build_filename
from .forwarder import send_with_attachments
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
    """PDF attachments pass through unchanged. If none exist, render the email
    body to PDF. Image attachments (photographed receipts) are individually
    wrapped into a minimal <img> HTML page and rendered to PDF. Anything else
    (docx/xlsx/zip/...) is logged and skipped — Playwright renders HTML, it
    does not convert arbitrary office formats. All outputs are named
    [date]-[sender]-[amount]-[currency].pdf regardless of source, so a PDF
    attachment forwarded as-is gets the same naming as a rendered body."""
    pdf_bytes_list: list[bytes] = []
    has_pdf = any(ct == "application/pdf" for _, ct, _ in attachments)

    if has_pdf:
        pdf_bytes_list.extend(data for _, ct, data in attachments if ct == "application/pdf")
    else:
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
            send_with_attachments(username, app_password, DEST_EMAIL, f"[rec] {subject}", body, pdfs)

            mark_forwarded(state, gm_msgid, subject, datetime.now(timezone.utc).isoformat())
            save_state(state)
            move_to_out_label(imap, uid)
    finally:
        imap.logout()


def _touch_heartbeat() -> None:
    path = Path(HEARTBEAT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def run() -> None:
    log.info(
        "rec: watcher started - watching label '%s' (forwarded mail moves to '%s'), polling every %ss (test_mode=%s)",
        GMAIL_LABEL_IN,
        GMAIL_LABEL_OUT,
        POLL_SECONDS,
        TEST_MODE,
    )
    signal.signal(signal.SIGTERM, lambda *_: (close_browser(), sys.exit(0)))

    while True:
        try:
            process_once()
        except Exception:
            log.exception("rec: unhandled error during poll cycle")

        _touch_heartbeat()

        if TEST_MODE:
            log.info("rec: TEST_MODE=true - exiting after single poll cycle")
            break

        time.sleep(POLL_SECONDS)

    close_browser()
