import json
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
