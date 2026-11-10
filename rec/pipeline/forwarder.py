import smtplib
from email.message import EmailMessage

from ..core.config import SMTP_HOST, SMTP_PORT
from ..core.logging_setup import log


def _one_line(value: str) -> str:
    """Collapse CR/LF and other whitespace runs so the value is header-safe."""
    return " ".join(value.split())


def send_with_attachments(
    smtp_username: str,
    smtp_password: str,
    to_addr: str,
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
) -> None:
    subject = _one_line(subject)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_username
    msg["To"] = to_addr
    msg.set_content(body)

    for filename, pdf_bytes in attachments:
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=_one_line(filename))

    # Same Gmail account/App Password serves both IMAP watch and SMTP relay.
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)

    log.info("forwarder: sent '%s' -> %s (%d attachment(s))", subject, to_addr, len(attachments))
