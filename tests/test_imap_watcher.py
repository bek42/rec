from email.message import EmailMessage
from unittest.mock import MagicMock

from rec.imap_watcher import extract_body_and_attachments, list_candidate_uids, move_to_out_label


def test_pdf_attachment_only():
    msg = EmailMessage()
    msg["Subject"] = "Receipt"
    msg.set_content("plain text body")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="receipt.pdf")

    html_body, text_body, attachments = extract_body_and_attachments(msg)

    assert text_body == "plain text body\n"
    assert html_body is None
    assert len(attachments) == 1
    filename, content_type, data = attachments[0]
    assert filename == "receipt.pdf"
    assert content_type == "application/pdf"
    assert data == b"%PDF-1.4 fake"


def test_jpeg_attachment_only():
    msg = EmailMessage()
    msg["Subject"] = "Receipt photo"
    msg.set_content("see attached")
    msg.add_attachment(b"\xff\xd8\xff fake jpeg", maintype="image", subtype="jpeg", filename="receipt.jpg")

    _, _, attachments = extract_body_and_attachments(msg)

    assert len(attachments) == 1
    filename, content_type, data = attachments[0]
    assert filename == "receipt.jpg"
    assert content_type == "image/jpeg"


def test_body_only_html():
    msg = EmailMessage()
    msg["Subject"] = "HTML receipt"
    msg.set_content("fallback text")
    msg.add_alternative("<html><body><p>Your receipt</p></body></html>", subtype="html")

    html_body, text_body, attachments = extract_body_and_attachments(msg)

    assert attachments == []
    assert text_body == "fallback text\n"
    assert "Your receipt" in html_body


def test_mixed_pdf_and_body():
    msg = EmailMessage()
    msg["Subject"] = "Mixed"
    msg.set_content("body text")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="receipt.pdf")
    msg.add_attachment(b"\xff\xd8\xff fake jpeg", maintype="image", subtype="jpeg", filename="photo.jpg")

    html_body, text_body, attachments = extract_body_and_attachments(msg)

    assert len(attachments) == 2
    content_types = {ct for _, ct, _ in attachments}
    assert content_types == {"application/pdf", "image/jpeg"}


def test_move_to_out_label_adds_and_removes():
    imap = MagicMock()
    imap.uid.return_value = ("OK", [None])

    move_to_out_label(imap, b"123")

    imap.uid.assert_any_call("STORE", b"123", "+X-GM-LABELS", '("Receipts/Out")')
    imap.uid.assert_any_call("STORE", b"123", "-X-GM-LABELS", '("Receipts/In")')


def test_list_candidate_uids_searches_by_label_not_selected_mailbox():
    imap = MagicMock()
    imap.uid.return_value = ("OK", [b"1 2 3"])

    uids = list_candidate_uids(imap)

    imap.uid.assert_called_once_with("search", None, "X-GM-RAW", '"label:Receipts/In"')
    assert uids == [b"1", b"2", b"3"]
