import json

import rec.pipeline.llm_classify as llm_classify


class _FakeResponse:
    """Minimal context-manager stand-in for urllib's urlopen() result."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _openai_payload(vendor="MINT42", category="coffee", currency="EUR", amount="8.60"):
    content = json.dumps(
        {"vendor": vendor, "category": category, "currency": currency, "amount": amount}
    )
    return {"choices": [{"message": {"content": content}}]}


def _enable(monkeypatch, categories=None):
    monkeypatch.setattr(llm_classify, "OPENAI_ENABLED", True)
    monkeypatch.setattr(llm_classify, "OPENAI_API_KEY", "sk-test-123")
    if categories is not None:
        monkeypatch.setattr(llm_classify, "RECEIPT_CATEGORIES", categories)


def test_disabled_returns_none_without_any_network_call(monkeypatch):
    monkeypatch.setattr(llm_classify, "OPENAI_ENABLED", False)

    def _boom(*a, **k):
        raise AssertionError("urlopen should not be called when disabled")

    monkeypatch.setattr(llm_classify.urllib.request, "urlopen", _boom)
    assert llm_classify.classify_with_llm("2x Flat White 6.60") is None


def test_enabled_but_no_api_key_returns_none(monkeypatch):
    monkeypatch.setattr(llm_classify, "OPENAI_ENABLED", True)
    monkeypatch.setattr(llm_classify, "OPENAI_API_KEY", None)
    assert llm_classify.classify_with_llm("2x Flat White 6.60") is None


def test_blank_text_returns_none(monkeypatch):
    _enable(monkeypatch)
    assert llm_classify.classify_with_llm("") is None
    assert llm_classify.classify_with_llm("   ") is None
    assert llm_classify.classify_with_llm(None) is None


def test_successful_classification(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        llm_classify.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse(_openai_payload()),
    )
    result = llm_classify.classify_with_llm("2x Flat White 6.60\nGESAMT 8.60")
    assert result == {"vendor": "MINT42", "category": "coffee", "currency": "EUR", "amount": "8.60"}


def test_category_outside_configured_list_is_dropped(monkeypatch):
    _enable(monkeypatch, categories=["coffee", "meal", "misc"])
    monkeypatch.setattr(
        llm_classify.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse(_openai_payload(category="entertainment")),
    )
    result = llm_classify.classify_with_llm("some receipt")
    assert result["category"] is None
    # other fields survive even though the category was rejected
    assert result["vendor"] == "MINT42"
    assert result["amount"] == "8.60"


def test_network_failure_falls_back_to_none(monkeypatch):
    _enable(monkeypatch)

    def _raise(req, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_classify.urllib.request, "urlopen", _raise)
    assert llm_classify.classify_with_llm("2x Flat White 6.60") is None


def test_malformed_response_falls_back_to_none(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        llm_classify.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse({"choices": []}),
    )
    assert llm_classify.classify_with_llm("2x Flat White 6.60") is None


def test_response_with_no_usable_fields_returns_none(monkeypatch):
    _enable(monkeypatch)
    content = json.dumps({"vendor": "", "category": "nope", "currency": "", "amount": None})
    monkeypatch.setattr(
        llm_classify.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse({"choices": [{"message": {"content": content}}]}),
    )
    assert llm_classify.classify_with_llm("some receipt") is None
