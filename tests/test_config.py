import importlib


def _reload_config(monkeypatch, **env):
    monkeypatch.setenv("ENV_FILE_PATH", "/nonexistent/.env")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from rec.core import config

    return importlib.reload(config)


def test_test_mode_truthy_strings(monkeypatch):
    for value in ("true", "True", "1", "t"):
        config = _reload_config(monkeypatch, test_mode=value)
        assert config.TEST_MODE is True, f"expected {value!r} to be truthy"


def test_test_mode_falsy_strings(monkeypatch):
    for value in ("false", "False", "0", "", "no"):
        config = _reload_config(monkeypatch, test_mode=value)
        assert config.TEST_MODE is False, f"expected {value!r} to be falsy"


def test_poll_seconds_defaults_and_parses(monkeypatch):
    monkeypatch.delenv("poll_seconds", raising=False)
    from rec.core import config

    config = importlib.reload(config)
    assert config.POLL_SECONDS == 300

    config = _reload_config(monkeypatch, poll_seconds="45")
    assert config.POLL_SECONDS == 45


def test_gmail_label_defaults(monkeypatch):
    monkeypatch.delenv("gmail_label_in", raising=False)
    monkeypatch.delenv("gmail_label_out", raising=False)
    from rec.core import config

    config = importlib.reload(config)
    assert config.GMAIL_LABEL_IN == "Receipts/In"
    assert config.GMAIL_LABEL_OUT == "Receipts/Out"


def test_subject_trigger_default(monkeypatch):
    monkeypatch.delenv("subject_trigger", raising=False)
    from rec.core import config

    config = importlib.reload(config)
    assert config.SUBJECT_TRIGGER == "[rec]"


def test_http_channel_defaults(monkeypatch):
    for var in (
        "http_enabled",
        "http_bind",
        "http_port",
        "http_max_upload_bytes",
        "http_result_timeout",
        "key_http_token",
        "key_http_infisical_section",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("key_gmail_infisical_section", "az-keyvault-smtp")
    from rec.core import config

    config = importlib.reload(config)
    assert config.HTTP_ENABLED is False
    assert config.HTTP_BIND == "0.0.0.0"
    assert config.HTTP_PORT == 8080
    assert config.HTTP_MAX_UPLOAD_BYTES == 25 * 1024 * 1024
    assert config.HTTP_RESULT_TIMEOUT == 60
    assert config.key_http_token == "rec-http-token"
    # Falls back to the Gmail Infisical section when unset.
    assert config.key_http_infisical_section == "az-keyvault-smtp"


def test_http_channel_overrides(monkeypatch):
    config = _reload_config(
        monkeypatch,
        http_enabled="true",
        http_port="9000",
        http_max_upload_bytes="1024",
        key_http_infisical_section="az-keyvault-rec-http",
    )
    assert config.HTTP_ENABLED is True
    assert config.HTTP_PORT == 9000
    assert config.HTTP_MAX_UPLOAD_BYTES == 1024
    assert config.key_http_infisical_section == "az-keyvault-rec-http"


def test_ocr_defaults(monkeypatch):
    for var in ("ocr_enabled", "ocr_langs", "tesseract_cmd", "ocr_timeout"):
        monkeypatch.delenv(var, raising=False)
    from rec.core import config

    config = importlib.reload(config)
    assert config.OCR_ENABLED is True
    assert config.OCR_LANGS == "eng+deu"
    assert config.TESSERACT_CMD == ""
    assert config.OCR_TIMEOUT == 30


def test_ocr_overrides(monkeypatch):
    config = _reload_config(
        monkeypatch,
        ocr_enabled="false",
        ocr_langs="eng",
        tesseract_cmd="/usr/bin/tesseract",
        ocr_timeout="10",
    )
    assert config.OCR_ENABLED is False
    assert config.OCR_LANGS == "eng"
    assert config.TESSERACT_CMD == "/usr/bin/tesseract"
    assert config.OCR_TIMEOUT == 10


def test_ocr_enabled_truthy_strings(monkeypatch):
    for value in ("true", "True", "1", "t"):
        config = _reload_config(monkeypatch, ocr_enabled=value)
        assert config.OCR_ENABLED is True, f"expected {value!r} to be truthy"
