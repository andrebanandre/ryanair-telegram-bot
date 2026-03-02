"""Chat registry — persist Telegram chat IDs to a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CHATS_FILE = Path("./data/chats.json")


def load_chats(path: Path = DEFAULT_CHATS_FILE) -> list[dict]:
    """Return list of registered chat records."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def register_chat(
    chat_id: int,
    first_name: str = "",
    username: str = "",
    path: Path = DEFAULT_CHATS_FILE,
) -> bool:
    """Add chat to registry if not already present. Returns True if newly added."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chats = load_chats(path)
    if any(c["chat_id"] == chat_id for c in chats):
        return False
    chats.append({"chat_id": chat_id, "first_name": first_name, "username": username})
    path.write_text(json.dumps(chats, indent=2))
    return True
