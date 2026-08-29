"""
http_server.py — Optional HTTP upload channel for rec.

The primary ingress is the Gmail/IMAP poll loop (poller.py). This module adds a
second, lower-latency channel: a phone automation (e.g. MacroDroid) captures a
photo of a receipt and POSTs it straight to the running container, which feeds
it through the *same* normalize-to-PDF + SMTP-forward pipeline as an emailed
attachment. The email flow is unchanged.

Why a hand-rolled http.server instead of a framework: rec is otherwise
sync/stdlib-only (imaplib, smtplib, email) and this is a single authenticated
endpoint. A framework would be a new declared dependency and would bust the
Docker deps + Chromium layers on every version bump for no real gain.

Why the handler only enqueues work: Playwright's sync API binds its event loop
to the thread that first started Chromium (the poll-loop thread). A request
handler running in the HTTP server's own thread therefore must not call the
renderer directly. Instead handle_upload() validates the request and builds an
HttpUpload job; the poll loop drains the queue and does all Playwright / SMTP /
state-file work on its single thread (see poller._drain_http_queue).
"""

from __future__ import annotations

import email
import hmac
import json
import queue
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping, NamedTuple

from .config import HTTP_BIND, HTTP_MAX_UPLOAD_BYTES, HTTP_PORT, HTTP_RESULT_TIMEOUT
from .logging_setup import log
from .secrets import get_http_token

# Content types normalize_to_pdfs (poller.py) knows how to render into a PDF.
_ACCEPTED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_UPLOAD_PATH = "/upload"


class HttpUpload(NamedTuple):
    """One validated upload waiting to be forwarded on the poll-loop thread."""

    subject: str
    sender: str
    date: str
    attachments: list[tuple[str, str, bytes]]
    result_q: queue.Queue


def _sniff_image_type(data: bytes) -> str | None:
    """Best-effort content sniff from magic bytes, for clients that don't set a
    useful Content-Type."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
        return "image/heic"
    return None


def _parse_upload(headers: Mapping[str, str], body: bytes) -> tuple[str, str, bytes]:
    """Return (filename, content_type, data). Accepts either a raw image body or
    a multipart/form-data upload (MacroDroid's "file to upload" field)."""
    content_type = headers.get("Content-Type") or ""

    if content_type.lower().startswith("multipart/form-data"):
        # Rebuild a minimal MIME document so the stdlib email parser can split
        # the parts — cgi.FieldStorage was removed in Python 3.13. Keep the
        # header verbatim: the boundary token is case-sensitive.
        raw = (
            b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        parsed = email.message_from_bytes(raw)
        for part in parsed.walk():
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            return part.get_filename() or "upload", (part.get_content_type() or "").lower(), payload
        return "upload", "application/octet-stream", b""

    filename = headers.get("X-Filename") or "upload"
    return filename, content_type.split(";")[0].strip().lower(), body


def handle_upload(
    headers: Mapping[str, str], body: bytes
) -> tuple[int, dict, HttpUpload | None]:
    """Pure request core — no sockets, unit-tested directly. Checks the bearer
    token, upload size and image type; on success returns (200, {}, job) with a
    job ready to enqueue. On any rejection returns (status, error_body, None)."""
    expected = get_http_token()
    scheme, _, token = headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token, expected):
        return 401, {"status": "error", "detail": "bad or missing bearer token"}, None

    if len(body) > HTTP_MAX_UPLOAD_BYTES:
        return (
            413,
            {"status": "error", "detail": f"upload exceeds {HTTP_MAX_UPLOAD_BYTES} bytes"},
            None,
        )

    filename, content_type, data = _parse_upload(headers, body)
    if not data:
        return 400, {"status": "error", "detail": "empty upload"}, None

    if content_type not in _ACCEPTED_TYPES:
        sniffed = _sniff_image_type(data)
        if sniffed in _ACCEPTED_TYPES:
            content_type = sniffed
        elif sniffed == "image/heic":
            return (
                415,
                {
                    "status": "error",
                    "detail": "HEIC is not supported — set the capture to save JPEG or PNG",
                },
                None,
            )
        else:
            return (
                415,
                {"status": "error", "detail": f"unsupported content type {content_type or 'unknown'}"},
                None,
            )

    now = datetime.now(timezone.utc)
    job = HttpUpload(
        subject=headers.get("X-Subject") or f"photo {now:%Y-%m-%d %H:%M}",
        sender=headers.get("X-Source") or "macrodroid",
        date=format_datetime(now),
        attachments=[(filename, content_type, data)],
        result_q=queue.Queue(maxsize=1),
    )
    return 200, {}, job


class _UploadHandler(BaseHTTPRequestHandler):
    server_version = "rec/http"

    def log_message(self, fmt: str, *args) -> None:
        # BaseHTTPRequestHandler logs every request straight to stderr by
        # default — route it through rec's logger instead.
        log.info("http_server: " + fmt, *args)

    def _respond(self, status: int, payload: dict) -> None:
        blob = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self) -> None:  # noqa: N802 — stdlib-mandated name
        if self.path.rstrip("/") != _UPLOAD_PATH:
            self._respond(404, {"status": "error", "detail": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > HTTP_MAX_UPLOAD_BYTES:
            self._respond(413, {"status": "error", "detail": "upload too large"})
            return
        body = self.rfile.read(length) if length else b""

        try:
            status, payload, job = handle_upload(self.headers, body)
        except Exception as exc:
            log.exception("http_server: failed to handle upload")
            self._respond(500, {"status": "error", "detail": str(exc)})
            return

        if job is None:
            self._respond(status, payload)
            return

        # Hand off to the poll-loop thread and wait for the real outcome so the
        # caller (the phone) gets a meaningful response.
        self.server.job_q.put(job)
        try:
            outcome, detail = job.result_q.get(timeout=HTTP_RESULT_TIMEOUT)
        except queue.Empty:
            self._respond(504, {"status": "error", "detail": "processing timed out"})
            return

        if outcome == "ok":
            self._respond(200, {"status": "forwarded", "files": detail})
        else:
            self._respond(502, {"status": "error", "detail": detail})


class _UploadServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], job_q: queue.Queue) -> None:
        super().__init__(addr, _UploadHandler)
        self.job_q = job_q


def build_server(job_q: queue.Queue) -> _UploadServer:
    """Create (but do not start) the upload server. Caller runs serve_forever()
    in a daemon thread and calls shutdown() on SIGTERM."""
    server = _UploadServer((HTTP_BIND, HTTP_PORT), job_q)
    log.info("http_server: listening on %s:%s%s", HTTP_BIND, HTTP_PORT, _UPLOAD_PATH)
    return server
