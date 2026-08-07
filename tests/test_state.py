from rec import state


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
