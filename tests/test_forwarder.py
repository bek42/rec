from email.message import EmailMessage

from rec.pipeline import forwarder


class _FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def test_newlines_in_subject_and_filename_do_not_raise(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(forwarder.smtplib, "SMTP", _FakeSMTP)
    forwarder.send_with_attachments(
        "u@x.com", "pw", "d@x.com",
        "[rec] receipt-LOsteria - Mulheim\n Dusseldorfer-2026.pdf",
        "body",
        [("receipt-LOsteria - Mulheim\r\n Dusseldorfer.pdf", b"%PDF-1.4")],
    )
    msg = _FakeSMTP.sent[0]
    assert msg["Subject"] == "[rec] receipt-LOsteria - Mulheim Dusseldorfer-2026.pdf"
    assert "\n" not in next(msg.iter_attachments()).get_filename()
