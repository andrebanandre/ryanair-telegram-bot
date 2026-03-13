"""Tests for buchbinder_trackers CRUD and _format_result from buchbinder_conv."""

from __future__ import annotations

import pytest
from pathlib import Path

from ryanair_tracker.buchbinder_trackers import (
    MAX_PRICE_HISTORY,
    add_buchbinder_tracker,
    append_buchbinder_price,
    delete_buchbinder_tracker,
    get_buchbinder_tracker,
    get_user_buchbinder_trackers,
    load_buchbinder_trackers,
    update_buchbinder_tracker,
)
from ryanair_tracker.bot.buchbinder_conv import _format_result


BASE = {
    "chat_id": 12345,
    "name": "VIE Rental June",
    "pickup": "VIE",
    "dropoff": "VIE",
    "rental_days": 7,
    "date_from": "2026-06-01",
    "date_to": "2026-06-30",
    "hour": 8,
    "minute": 0,
}

SAMPLE_ENTRY = {
    "ts": "2026-03-13T08:00:00",
    "min_price": 210.0,
    "per_day": 30.0,
    "best_pickup": "2026-06-05",
    "results": [
        {
            "pickup": "2026-06-05",
            "dropoff": "2026-06-12",
            "price": 210.0,
            "per_day": 30.0,
            "car": "Economy (VW Polo)",
            "gear": "Manual",
            "unlimited": True,
        },
        {
            "pickup": "2026-06-06",
            "dropoff": "2026-06-13",
            "price": 245.0,
            "per_day": 35.0,
            "car": "Compact (VW Golf)",
            "gear": "Auto",
            "unlimited": False,
        },
    ],
}


# ── add / get ─────────────────────────────────────────────────────────────────

def test_add_assigns_id(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    assert "id" in t
    assert t["id"]


def test_add_initialises_empty_history(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    assert t["price_history"] == []


def test_add_and_get_round_trip(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    fetched = get_buchbinder_tracker(t["id"], p)
    assert fetched is not None
    assert fetched["name"] == "VIE Rental June"
    assert fetched["pickup"] == "VIE"
    assert fetched["rental_days"] == 7


def test_get_nonexistent_returns_none(tmp_path):
    p = tmp_path / "buch.json"
    assert get_buchbinder_tracker("ghost", p) is None


def test_get_from_missing_file_returns_none(tmp_path):
    p = tmp_path / "missing.json"
    assert get_buchbinder_tracker("any", p) is None


# ── list ──────────────────────────────────────────────────────────────────────

def test_get_user_buchbinder_trackers_empty(tmp_path):
    p = tmp_path / "buch.json"
    assert get_user_buchbinder_trackers(12345, p) == []


def test_get_user_buchbinder_trackers_own(tmp_path):
    p = tmp_path / "buch.json"
    add_buchbinder_tracker(dict(BASE), p)
    add_buchbinder_tracker({**BASE, "name": "Second"}, p)
    assert len(get_user_buchbinder_trackers(12345, p)) == 2


def test_get_user_buchbinder_trackers_isolation(tmp_path):
    p = tmp_path / "buch.json"
    add_buchbinder_tracker(dict(BASE), p)
    add_buchbinder_tracker({**BASE, "chat_id": 99999, "name": "Other"}, p)
    assert len(get_user_buchbinder_trackers(12345, p)) == 1
    assert len(get_user_buchbinder_trackers(99999, p)) == 1


def test_load_buchbinder_trackers_all(tmp_path):
    p = tmp_path / "buch.json"
    add_buchbinder_tracker(dict(BASE), p)
    add_buchbinder_tracker({**BASE, "chat_id": 99999}, p)
    assert len(load_buchbinder_trackers(p)) == 2


# ── update ────────────────────────────────────────────────────────────────────

def test_update_name(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    assert update_buchbinder_tracker(t["id"], {"name": "New name"}, p) is True
    assert get_buchbinder_tracker(t["id"], p)["name"] == "New name"


def test_update_preserves_price_history(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    append_buchbinder_price(t["id"], {"min_price": 200.0, "ts": "2026-03-01T08:00:00"}, p)
    update_buchbinder_tracker(t["id"], {"name": "Renamed"}, p)
    fetched = get_buchbinder_tracker(t["id"], p)
    assert len(fetched["price_history"]) == 1


def test_update_preserves_id(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    update_buchbinder_tracker(t["id"], {"hour": 6}, p)
    assert get_buchbinder_tracker(t["id"], p)["id"] == t["id"]


def test_update_nonexistent_returns_false(tmp_path):
    p = tmp_path / "buch.json"
    assert update_buchbinder_tracker("ghost", {"name": "x"}, p) is False


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_removes(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    assert delete_buchbinder_tracker(t["id"], p) is True
    assert get_buchbinder_tracker(t["id"], p) is None


def test_delete_leaves_others(tmp_path):
    p = tmp_path / "buch.json"
    t1 = add_buchbinder_tracker(dict(BASE), p)
    t2 = add_buchbinder_tracker({**BASE, "name": "Keep"}, p)
    delete_buchbinder_tracker(t1["id"], p)
    assert get_buchbinder_tracker(t2["id"], p) is not None


def test_delete_nonexistent_returns_false(tmp_path):
    p = tmp_path / "buch.json"
    assert delete_buchbinder_tracker("ghost", p) is False


# ── append_buchbinder_price ───────────────────────────────────────────────────

def test_append_price_stores_entry(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    entry = {"min_price": 210.0, "ts": "2026-03-05T08:00:00"}
    append_buchbinder_price(t["id"], entry, p)
    fetched = get_buchbinder_tracker(t["id"], p)
    assert len(fetched["price_history"]) == 1
    assert fetched["price_history"][0]["min_price"] == 210.0


def test_append_price_caps_at_max(tmp_path):
    p = tmp_path / "buch.json"
    t = add_buchbinder_tracker(dict(BASE), p)
    for i in range(MAX_PRICE_HISTORY + 5):
        append_buchbinder_price(
            t["id"],
            {"min_price": float(i), "ts": f"2026-03-{i % 28 + 1:02d}"},
            p,
        )
    fetched = get_buchbinder_tracker(t["id"], p)
    assert len(fetched["price_history"]) == MAX_PRICE_HISTORY


def test_append_price_unknown_tracker_noop(tmp_path):
    p = tmp_path / "buch.json"
    # Should not raise
    append_buchbinder_price("ghost", {"min_price": 100.0, "ts": "2026-03-01"}, p)


# ── _format_result ────────────────────────────────────────────────────────────

def _make_tracker(**kwargs) -> dict:
    return {**BASE, "id": "test-id", "price_history": [], **kwargs}


def test_format_no_results():
    tracker = _make_tracker()
    entry = {"ts": "2026-03-13T08:00:00", "min_price": None, "per_day": None,
             "best_pickup": None, "results": []}
    msg = _format_result(tracker, entry)
    assert "No available cars" in msg
    assert "VIE Rental June" in msg


def test_format_shows_name_and_route():
    tracker = _make_tracker()
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "VIE Rental June" in msg
    assert "VIE → VIE" in msg
    assert "2026-06-01" in msg
    assert "2026-06-30" in msg


def test_format_shows_best_price():
    tracker = _make_tracker()
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "210" in msg
    assert "30" in msg


def test_format_shows_top_dates():
    tracker = _make_tracker()
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "Jun-05" in msg
    assert "Jun-12" in msg
    assert "Economy (VW Polo)" in msg


def test_format_gear_auto():
    tracker = _make_tracker()
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "Auto" in msg


def test_format_gear_manual():
    tracker = _make_tracker()
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "Manual" in msg


def test_format_unlimited_km():
    tracker = _make_tracker()
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "∞" in msg


def test_format_trend_down():
    tracker = _make_tracker(price_history=[
        {"min_price": 280.0, "ts": "2026-03-12T08:00:00"}
    ])
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "↓" in msg


def test_format_trend_up():
    tracker = _make_tracker(price_history=[
        {"min_price": 150.0, "ts": "2026-03-12T08:00:00"}
    ])
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "↑" in msg


def test_format_no_trend_without_history():
    tracker = _make_tracker(price_history=[])
    msg = _format_result(tracker, SAMPLE_ENTRY)
    assert "↑" not in msg
    assert "↓" not in msg


def test_format_no_trend_small_change():
    tracker = _make_tracker(price_history=[
        {"min_price": 210.5, "ts": "2026-03-12T08:00:00"}
    ])
    msg = _format_result(tracker, SAMPLE_ENTRY)
    # 0.24% change — below 0.5% threshold
    assert "↑" not in msg
    assert "↓" not in msg
