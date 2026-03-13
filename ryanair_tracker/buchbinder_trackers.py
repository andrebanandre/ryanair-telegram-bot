"""Buchbinder tracker storage — persist car rental price tracker configs to buchbinder_trackers.json."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

DEFAULT_BUCHBINDER_FILE = Path("./data/buchbinder_trackers.json")
MAX_PRICE_HISTORY = 30


def load_buchbinder_trackers(path: Path = DEFAULT_BUCHBINDER_FILE) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save(trackers: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trackers, indent=2))


def get_user_buchbinder_trackers(chat_id: int, path: Path = DEFAULT_BUCHBINDER_FILE) -> list[dict]:
    return [t for t in load_buchbinder_trackers(path) if t["chat_id"] == chat_id]


def get_buchbinder_tracker(tracker_id: str, path: Path = DEFAULT_BUCHBINDER_FILE) -> dict | None:
    return next((t for t in load_buchbinder_trackers(path) if t["id"] == tracker_id), None)


def add_buchbinder_tracker(tracker: dict, path: Path = DEFAULT_BUCHBINDER_FILE) -> dict:
    trackers = load_buchbinder_trackers(path)
    tracker = {**tracker, "id": str(uuid.uuid4()), "price_history": []}
    trackers.append(tracker)
    _save(trackers, path)
    return tracker


def update_buchbinder_tracker(
    tracker_id: str, updates: dict, path: Path = DEFAULT_BUCHBINDER_FILE
) -> bool:
    trackers = load_buchbinder_trackers(path)
    for i, t in enumerate(trackers):
        if t["id"] == tracker_id:
            # preserve price_history across edits
            trackers[i] = {
                **t,
                **updates,
                "id": tracker_id,
                "price_history": t.get("price_history", []),
            }
            _save(trackers, path)
            return True
    return False


def delete_buchbinder_tracker(tracker_id: str, path: Path = DEFAULT_BUCHBINDER_FILE) -> bool:
    trackers = load_buchbinder_trackers(path)
    new = [t for t in trackers if t["id"] != tracker_id]
    if len(new) == len(trackers):
        return False
    _save(new, path)
    return True


def append_buchbinder_price(
    tracker_id: str, entry: dict, path: Path = DEFAULT_BUCHBINDER_FILE
) -> None:
    """Append one price-check snapshot to the tracker's history."""
    trackers = load_buchbinder_trackers(path)
    for i, t in enumerate(trackers):
        if t["id"] == tracker_id:
            history = list(t.get("price_history", []))
            history.append(entry)
            trackers[i]["price_history"] = history[-MAX_PRICE_HISTORY:]
            _save(trackers, path)
            return
