from datetime import datetime, timedelta, timezone

from rec.core import state


def test_load_state_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DEDUP_STATE_PATH", str(tmp_path / "dedup.json"))
    assert state.load_state() == {}


def test_load_state_corrupt_file_returns_empty_dict(tmp_path, monkeypatch):
    path = tmp_path / "dedup.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(state, "DEDUP_STATE_PATH", str(path))
    assert state.load_state() == {}


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "dedup.json"
    monkeypatch.setattr(state, "DEDUP_STATE_PATH", str(path))

    data = state.load_state()
    state.mark_forwarded(data, "gm-123", "Receipt for coffee", "2026-08-07T00:00:00+00:00")
    state.save_state(data)

    reloaded = state.load_state()
    assert reloaded == {
        "gm-123": {"subject": "Receipt for coffee", "forwarded_at": "2026-08-07T00:00:00+00:00"}
    }


def test_already_forwarded():
    data = {"gm-123": {"subject": "x", "forwarded_at": "y"}}
    assert state.already_forwarded(data, "gm-123") is True
    assert state.already_forwarded(data, "gm-999") is False


def test_forwarded_within_absent_entry_is_false():
    assert state.forwarded_within({}, "gm-123", 600) is False


def test_forwarded_within_recent_entry_is_true():
    now = datetime.now(timezone.utc)
    data = {"gm-123": {"subject": "x", "forwarded_at": (now - timedelta(seconds=30)).isoformat()}}
    assert state.forwarded_within(data, "gm-123", 600) is True


def test_forwarded_within_old_entry_is_false():
    now = datetime.now(timezone.utc)
    data = {"gm-123": {"subject": "x", "forwarded_at": (now - timedelta(days=3)).isoformat()}}
    assert state.forwarded_within(data, "gm-123", 600) is False


def test_forwarded_within_malformed_timestamp_defaults_to_true():
    # Conservative default: can't tell how old it is, so don't double-send.
    data = {"gm-123": {"subject": "x", "forwarded_at": "not-a-timestamp"}}
    assert state.forwarded_within(data, "gm-123", 600) is True
