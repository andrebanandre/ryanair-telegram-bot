"""Tests for schedule CRUD persistence."""
from ryanair_tracker.schedules import (
    add_schedule,
    delete_schedule,
    get_schedule,
    get_user_schedules,
    load_schedules,
    update_schedule,
)
from tests.conftest import SAMPLE_SCHEDULE


# ── add / get ─────────────────────────────────────────────────────────────────

def test_add_assigns_id(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    assert "id" in s
    assert s["id"]  # non-empty


def test_add_and_get_round_trip(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    fetched = get_schedule(s["id"], tmp_schedules)
    assert fetched is not None
    assert fetched["name"] == "Test VIE→GR"
    assert fetched["chat_id"] == 12345


def test_get_nonexistent_returns_none(tmp_schedules):
    assert get_schedule("does-not-exist", tmp_schedules) is None


def test_get_from_missing_file_returns_none(tmp_schedules):
    assert get_schedule("any-id", tmp_schedules) is None


# ── list ──────────────────────────────────────────────────────────────────────

def test_get_user_schedules_empty(tmp_schedules):
    assert get_user_schedules(12345, tmp_schedules) == []


def test_get_user_schedules_returns_own(tmp_schedules):
    add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    add_schedule({**SAMPLE_SCHEDULE, "name": "Second"}, tmp_schedules)
    schedules = get_user_schedules(12345, tmp_schedules)
    assert len(schedules) == 2


def test_get_user_schedules_isolates_users(tmp_schedules):
    add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)                          # user 12345
    add_schedule({**SAMPLE_SCHEDULE, "chat_id": 99999, "name": "Other"}, tmp_schedules)  # user 99999
    assert len(get_user_schedules(12345, tmp_schedules)) == 1
    assert len(get_user_schedules(99999, tmp_schedules)) == 1
    assert get_user_schedules(99999, tmp_schedules)[0]["name"] == "Other"


def test_load_schedules_all(tmp_schedules):
    add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    add_schedule({**SAMPLE_SCHEDULE, "chat_id": 99999}, tmp_schedules)
    all_schedules = load_schedules(tmp_schedules)
    assert len(all_schedules) == 2


# ── update ────────────────────────────────────────────────────────────────────

def test_update_name(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    result = update_schedule(s["id"], {"name": "Updated"}, tmp_schedules)
    assert result is True
    assert get_schedule(s["id"], tmp_schedules)["name"] == "Updated"


def test_update_preserves_id(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    update_schedule(s["id"], {"name": "New Name"}, tmp_schedules)
    fetched = get_schedule(s["id"], tmp_schedules)
    assert fetched["id"] == s["id"]


def test_update_nonexistent_returns_false(tmp_schedules):
    assert update_schedule("ghost-id", {"name": "x"}, tmp_schedules) is False


def test_update_partial_leaves_other_fields(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    update_schedule(s["id"], {"hour": 6}, tmp_schedules)
    fetched = get_schedule(s["id"], tmp_schedules)
    assert fetched["hour"] == 6
    assert fetched["origin"] == "VIE"  # untouched


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_removes_schedule(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    result = delete_schedule(s["id"], tmp_schedules)
    assert result is True
    assert get_schedule(s["id"], tmp_schedules) is None


def test_delete_leaves_others_intact(tmp_schedules):
    s1 = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    s2 = add_schedule({**SAMPLE_SCHEDULE, "name": "Keep me"}, tmp_schedules)
    delete_schedule(s1["id"], tmp_schedules)
    assert get_schedule(s2["id"], tmp_schedules) is not None


def test_delete_nonexistent_returns_false(tmp_schedules):
    assert delete_schedule("ghost-id", tmp_schedules) is False


def test_delete_all_leaves_empty(tmp_schedules):
    s = add_schedule(dict(SAMPLE_SCHEDULE), tmp_schedules)
    delete_schedule(s["id"], tmp_schedules)
    assert get_user_schedules(12345, tmp_schedules) == []
