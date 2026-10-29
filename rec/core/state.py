import json
from datetime import datetime, timezone
from pathlib import Path

from .config import DEDUP_STATE_PATH
from .logging_setup import log


def load_state() -> dict:
    try:
        return json.loads(Path(DEDUP_STATE_PATH).read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        log.warning("state: corrupt state file (%s) - resetting", exc)
        return {}


def save_state(state: dict) -> None:
    path = Path(DEDUP_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def already_forwarded(state: dict, gm_msgid: str) -> bool:
    return gm_msgid in state


def mark_forwarded(state: dict, gm_msgid: str, subject: str, forwarded_at: str) -> None:
    state[gm_msgid] = {"subject": subject, "forwarded_at": forwarded_at}


def forwarded_within(state: dict, gm_msgid: str, seconds: int) -> bool:
    """True if gm_msgid is in state and was forwarded less than `seconds` ago.
    Used to tell a genuine crash-recovery race (relabelled GMAIL_LABEL_IN
    again moments after a send that crashed before move_to_out_label ran)
    apart from a deliberate relabel days/weeks later to force a reprocess —
    see process_once(). A missing or malformed timestamp is treated as
    "recent" (the safe default: don't double-send)."""
    entry = state.get(gm_msgid)
    if not entry:
        return False
    try:
        forwarded_at = datetime.fromisoformat(entry["forwarded_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return (datetime.now(timezone.utc) - forwarded_at).total_seconds() < seconds
