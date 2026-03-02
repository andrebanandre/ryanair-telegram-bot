"""Schedule storage — persist job configs to schedules.json."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

DEFAULT_SCHEDULES_FILE = Path("./schedules.json")


def load_schedules(path: Path = DEFAULT_SCHEDULES_FILE) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save(schedules: list[dict], path: Path) -> None:
    path.write_text(json.dumps(schedules, indent=2))


def get_user_schedules(chat_id: int, path: Path = DEFAULT_SCHEDULES_FILE) -> list[dict]:
    return [s for s in load_schedules(path) if s["chat_id"] == chat_id]


def get_schedule(schedule_id: str, path: Path = DEFAULT_SCHEDULES_FILE) -> dict | None:
    return next((s for s in load_schedules(path) if s["id"] == schedule_id), None)


def add_schedule(schedule: dict, path: Path = DEFAULT_SCHEDULES_FILE) -> dict:
    schedules = load_schedules(path)
    schedule = {**schedule, "id": str(uuid.uuid4())}
    schedules.append(schedule)
    _save(schedules, path)
    return schedule


def update_schedule(schedule_id: str, updates: dict, path: Path = DEFAULT_SCHEDULES_FILE) -> bool:
    schedules = load_schedules(path)
    for i, s in enumerate(schedules):
        if s["id"] == schedule_id:
            schedules[i] = {**s, **updates, "id": schedule_id}
            _save(schedules, path)
            return True
    return False


def delete_schedule(schedule_id: str, path: Path = DEFAULT_SCHEDULES_FILE) -> bool:
    schedules = load_schedules(path)
    new = [s for s in schedules if s["id"] != schedule_id]
    if len(new) == len(schedules):
        return False
    _save(new, path)
    return True
