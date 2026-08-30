import email
import imaplib
import re
from email.message import Message

from ..core.config import GMAIL_LABEL_IN, GMAIL_LABEL_OUT, IMAP_HOST, SUBJECT_TRIGGER
from ..core.logging_setup import log

_GM_MSGID_RE = re.compile(rb"X-GM-MSGID (\d+)")


def connect(username: str, app_password: str) -> imaplib.IMAP4_SSL:
    """Selects Gmail's All Mail mailbox rather than GMAIL_LABEL_IN itself.
    Gmail's IMAP extension won't reliably apply a STORE that removes the
    X-GM-LABELS entry matching the currently *selected* mailbox (the STORE
    still reports OK, but the label silently stays put) - so move_to_out_label
    would never actually detach GMAIL_LABEL_IN if we selected it directly,
    leaving every processed message tagged with both labels forever and
    eligible for re-processing on any dedup-state loss."""
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(username, app_password)
    imap.select('"[Gmail]/All Mail"')
    return imap


def move_to_out_label(imap: imaplib.IMAP4_SSL, uid: bytes) -> None:
    """Gmail's IMAP extension: tag the message with GMAIL_LABEL_OUT and
    untag GMAIL_LABEL_IN, so it visibly moves between the two Gmail labels —
    this is the user-visible "processed" marker, on top of the local dedup
    state file (which guards against a crash between send and relabel)."""
    typ, _ = imap.uid("STORE", uid, "+X-GM-LABELS", f'("{GMAIL_LABEL_OUT}")')
    if typ != "OK":
        log.warning("imap_watcher: failed to add label '%s' to uid %s", GMAIL_LABEL_OUT, uid)
    typ, _ = imap.uid("STORE", uid, "-X-GM-LABELS", f'("{GMAIL_LABEL_IN}")')
    if typ != "OK":
        log.warning("imap_watcher: failed to remove label '%s' from uid %s", GMAIL_LABEL_IN, uid)


def _gm_raw_search(imap: imaplib.IMAP4_SSL, query: str) -> list[bytes]:
    """Runs a Gmail search-syntax query via the X-GM-RAW extension rather
    than selecting a label as the mailbox - see connect()'s docstring for
    why. IMAP quoted-string escaping (backslash then double-quote) is
    applied since query may itself contain a quoted phrase."""
    escaped = query.replace("\\", "\\\\").replace('"', '\\"')
    typ, data = imap.uid("search", None, "X-GM-RAW", f'"{escaped}"')
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _matches_subject_trigger(imap: imaplib.IMAP4_SSL, uid: bytes) -> bool:
    """Gmail's subject: search tokenizes on punctuation, so `subject:"[rec]"`
    also matches e.g. "Rec/Freestyle" or "bek42/rec" - it's only a coarse
    pre-filter. Confirm the literal marker is actually present, and skip
    auto-replies/out-of-office bounces (RFC 3834 Auto-Submitted), since one
    of our own forwarded subjects showing up in an autoresponder's "[rec]
    Original Subject" quote would otherwise get treated as a new trigger."""
    typ, data = imap.uid(
        "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT AUTO-SUBMITTED)])"
    )
    if typ != "OK" or not data or not data[0]:
        return False
    header = data[0][1].decode("utf-8", errors="replace")
    auto_submitted = re.search(r"(?im)^Auto-Submitted:\s*(\S+)", header)
    if auto_submitted and auto_submitted.group(1).lower() != "no":
        return False
    return SUBJECT_TRIGGER in header


def list_candidate_uids(imap: imaplib.IMAP4_SSL) -> list[bytes]:
    """Two ways into the forward pipeline: labelled GMAIL_LABEL_IN, or any
    Inbox message whose subject contains SUBJECT_TRIGGER - a manual trigger
    for mail that's awkward to label directly. Both feed the same
    dedup/forward logic in poller.py, so a message matching both is still
    only forwarded once."""
    uids = set(_gm_raw_search(imap, f"label:{GMAIL_LABEL_IN}"))
    subject_hits = _gm_raw_search(imap, f'in:inbox subject:"{SUBJECT_TRIGGER}"')
    uids.update(uid for uid in subject_hits if _matches_subject_trigger(imap, uid))
    return sorted(uids, key=int)


def fetch_gm_msgid(imap: imaplib.IMAP4_SSL, uid: bytes) -> str | None:
    """Gmail's IMAP extension: a message ID stable across labels/mailboxes,
    unlike UID which is only stable per-mailbox-per-session."""
    typ, data = imap.uid("fetch", uid, "(X-GM-MSGID)")
    if typ != "OK" or not data or not data[0]:
        return None
    match = _GM_MSGID_RE.search(data[0])
    return match.group(1).decode() if match else None


def fetch_message(imap: imaplib.IMAP4_SSL, uid: bytes) -> Message | None:
    typ, data = imap.uid("fetch", uid, "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        return None
    raw = data[0][1]
    return email.message_from_bytes(raw)


def extract_body_and_attachments(
    msg: Message,
) -> tuple[str | None, str | None, list[tuple[str, str, bytes]]]:
    """Returns (html_body, text_body, [(filename, content_type, bytes), ...]).

    A part is treated as an attachment if it has a Content-Disposition of
    "attachment" or carries a filename — same heuristic used by
    daily-mail-digest's gmail_client.py, adapted from Gmail-API JSON payloads
    to stdlib email.message.Message.walk().
    """
    html_body: str | None = None
    text_body: str | None = None
    attachments: list[tuple[str, str, bytes]] = []

    for part in msg.walk():
        if part.is_multipart():
            continue

        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition") or "")
        filename = part.get_filename()

        if filename or "attachment" in disposition.lower():
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append((filename or "attachment", content_type, payload))
            continue

        if content_type == "text/html" and html_body is None:
            payload = part.get_payload(decode=True)
            if payload:
                html_body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        elif content_type == "text/plain" and text_body is None:
            payload = part.get_payload(decode=True)
            if payload:
                text_body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")

    return html_body, text_body, attachments
