import importlib


def _reload_config(monkeypatch, **env):
    monkeypatch.setenv("ENV_FILE_PATH", "/nonexistent/.env")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from rec import config

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
    from rec import config

    config = importlib.reload(config)
    assert config.POLL_SECONDS == 300

    config = _reload_config(monkeypatch, poll_seconds="45")
    assert config.POLL_SECONDS == 45


def test_gmail_label_defaults(monkeypatch):
    monkeypatch.delenv("gmail_label_in", raising=False)
    monkeypatch.delenv("gmail_label_out", raising=False)
    from rec import config

    config = importlib.reload(config)
    assert config.GMAIL_LABEL_IN == "Receipts/In"
    assert config.GMAIL_LABEL_OUT == "Receipts/Out"
