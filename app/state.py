import json
from pathlib import Path

from app.config import settings

_state_file = Path(settings.state_dir) / "state.json"


def _ensure_dir():
    _state_file.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    _ensure_dir()
    if _state_file.exists():
        return json.loads(_state_file.read_text())
    return {}


def save_state(state: dict):
    _ensure_dir()
    _state_file.write_text(json.dumps(state, indent=2))
