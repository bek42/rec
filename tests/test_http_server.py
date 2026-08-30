import pytest

import rec.ingest.http_server as http_server

_TOKEN = "test-secret-token"
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _stub_token(monkeypatch):
    monkeypatch.setattr(http_server, "get_http_token", lambda: _TOKEN)


def _auth(token=_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_raw_jpeg_body_accepted():
    status, _, job = http_server.handle_upload(
        {**_auth(), "Content-Type": "image/jpeg", "X-Subject": "Costa 4.75 GBP"}, _JPEG
    )
    assert status == 200
    assert job is not None
    assert job.subject == "Costa 4.75 GBP"
    assert job.sender == "macrodroid"
    assert job.attachments == [("upload", "image/jpeg", _JPEG)]


def test_multipart_png_accepted():
    boundary = "X"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="shot.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + _PNG + f"\r\n--{boundary}--\r\n".encode()

    status, _, job = http_server.handle_upload(
        {**_auth(), "Content-Type": f"multipart/form-data; boundary={boundary}"}, body
    )
    assert status == 200
    assert job.attachments == [("shot.png", "image/png", _PNG)]


def test_missing_token_rejected():
    status, _, job = http_server.handle_upload({"Content-Type": "image/jpeg"}, _JPEG)
    assert status == 401
    assert job is None


def test_wrong_token_rejected():
    status, _, job = http_server.handle_upload(
        {**_auth("nope"), "Content-Type": "image/jpeg"}, _JPEG
    )
    assert status == 401
    assert job is None


def test_oversize_rejected(monkeypatch):
    monkeypatch.setattr(http_server, "HTTP_MAX_UPLOAD_BYTES", 8)
    status, _, job = http_server.handle_upload(
        {**_auth(), "Content-Type": "image/jpeg"}, _JPEG
    )
    assert status == 413
    assert job is None


def test_heic_rejected():
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16
    status, body, job = http_server.handle_upload(
        {**_auth(), "Content-Type": "image/heic"}, heic
    )
    assert status == 415
    assert job is None
    assert "HEIC" in body["detail"]


def test_content_type_sniffed_from_magic_bytes():
    status, _, job = http_server.handle_upload(
        {**_auth(), "Content-Type": "application/octet-stream"}, _PNG
    )
    assert status == 200
    assert job.attachments[0][1] == "image/png"


def test_unsupported_type_rejected():
    status, _, job = http_server.handle_upload(
        {**_auth(), "Content-Type": "application/pdf"}, b"%PDF-1.7 not really"
    )
    assert status == 415
    assert job is None
