"""Tests for tracker CRUD persistence and format_track_result."""
from datetime import datetime

from ryanair_tracker.trackers import (
    add_tracker,
    append_price,
    delete_tracker,
    get_tracker,
    get_user_trackers,
    load_trackers,
    update_tracker,
)
from ryanair_tracker.bot.tracker_conv import format_track_result


BASE = {
    "chat_id": 12345,
    "name": "VIE→ATH June",
    "origin": "VIE",
    "dest": "ATH",
    "date_from": "2026-06-01",
    "date_to": "2026-06-08",
    "hour": 8,
    "minute": 0,
}

SAMPLE_RESULT = {
    "origin": "VIE",
    "destination": "ATH",
    "outbound_flight": "FR1234",
    "return_flight": "FR5678",
    "outbound_price": 89.0,
    "return_price": 75.0,
    "total_price": 164.0,
    "currency": "EUR",
    "nights": 7,
    "outbound_depart": "2026-06-01 06:30",
    "return_depart": "2026-06-08 10:15",
    "is_deal": False,
}


# ── add / get ─────────────────────────────────────────────────────────────────

def test_add_assigns_id(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    assert "id" in t
    assert t["id"]


def test_add_initialises_empty_history(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    assert t["price_history"] == []


def test_add_and_get_round_trip(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    fetched = get_tracker(t["id"], tmp_schedules)
    assert fetched is not None
    assert fetched["name"] == "VIE→ATH June"
    assert fetched["origin"] == "VIE"
    assert fetched["dest"] == "ATH"


def test_get_nonexistent_returns_none(tmp_schedules):
    assert get_tracker("ghost", tmp_schedules) is None


def test_get_from_missing_file_returns_none(tmp_schedules):
    assert get_tracker("any", tmp_schedules) is None


# ── list ──────────────────────────────────────────────────────────────────────

def test_get_user_trackers_empty(tmp_schedules):
    assert get_user_trackers(12345, tmp_schedules) == []


def test_get_user_trackers_own(tmp_schedules):
    add_tracker(dict(BASE), tmp_schedules)
    add_tracker({**BASE, "name": "Second"}, tmp_schedules)
    assert len(get_user_trackers(12345, tmp_schedules)) == 2


def test_get_user_trackers_isolation(tmp_schedules):
    add_tracker(dict(BASE), tmp_schedules)
    add_tracker({**BASE, "chat_id": 99999, "name": "Other"}, tmp_schedules)
    assert len(get_user_trackers(12345, tmp_schedules)) == 1
    assert len(get_user_trackers(99999, tmp_schedules)) == 1


def test_load_trackers_all(tmp_schedules):
    add_tracker(dict(BASE), tmp_schedules)
    add_tracker({**BASE, "chat_id": 99999}, tmp_schedules)
    assert len(load_trackers(tmp_schedules)) == 2


# ── update ────────────────────────────────────────────────────────────────────

def test_update_name(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    assert update_tracker(t["id"], {"name": "New name"}, tmp_schedules) is True
    assert get_tracker(t["id"], tmp_schedules)["name"] == "New name"


def test_update_preserves_price_history(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    append_price(t["id"], {"total_price": 164.0, "ts": "2026-03-01T08:00:00"}, tmp_schedules)
    update_tracker(t["id"], {"name": "Renamed"}, tmp_schedules)
    fetched = get_tracker(t["id"], tmp_schedules)
    assert len(fetched["price_history"]) == 1


def test_update_preserves_id(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    update_tracker(t["id"], {"hour": 6}, tmp_schedules)
    assert get_tracker(t["id"], tmp_schedules)["id"] == t["id"]


def test_update_nonexistent_returns_false(tmp_schedules):
    assert update_tracker("ghost", {"name": "x"}, tmp_schedules) is False


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_removes(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    assert delete_tracker(t["id"], tmp_schedules) is True
    assert get_tracker(t["id"], tmp_schedules) is None


def test_delete_leaves_others(tmp_schedules):
    t1 = add_tracker(dict(BASE), tmp_schedules)
    t2 = add_tracker({**BASE, "name": "Keep"}, tmp_schedules)
    delete_tracker(t1["id"], tmp_schedules)
    assert get_tracker(t2["id"], tmp_schedules) is not None


def test_delete_nonexistent_returns_false(tmp_schedules):
    assert delete_tracker("ghost", tmp_schedules) is False


# ── append_price ──────────────────────────────────────────────────────────────

def test_append_price_stores_entry(tmp_schedules):
    t = add_tracker(dict(BASE), tmp_schedules)
    entry = {"outbound_price": 89.0, "return_price": 75.0, "total_price": 164.0,
             "ts": "2026-03-05T08:00:00"}
    append_price(t["id"], entry, tmp_schedules)
    fetched = get_tracker(t["id"], tmp_schedules)
    assert len(fetched["price_history"]) == 1
    assert fetched["price_history"][0]["total_price"] == 164.0


def test_append_price_caps_at_max(tmp_schedules):
    from ryanair_tracker.trackers import MAX_PRICE_HISTORY
    t = add_tracker(dict(BASE), tmp_schedules)
    for i in range(MAX_PRICE_HISTORY + 5):
        append_price(t["id"], {"total_price": float(i), "ts": f"2026-03-{i % 28 + 1:02d}"},
                     tmp_schedules)
    fetched = get_tracker(t["id"], tmp_schedules)
    assert len(fetched["price_history"]) == MAX_PRICE_HISTORY


def test_append_price_unknown_tracker_noop(tmp_schedules):
    # Should not raise
    append_price("ghost", {"total_price": 100.0, "ts": "2026-03-01"}, tmp_schedules)


# ── format_track_result ───────────────────────────────────────────────────────

def _make_tracker(**kwargs) -> dict:
    return {**BASE, "id": "test-id", "price_history": [], **kwargs}


def test_format_no_results():
    tracker = _make_tracker()
    msg = format_track_result(tracker, [])
    assert "No flights found" in msg
    assert "VIE→ATH June" in msg


def test_format_shows_name_and_route():
    tracker = _make_tracker()
    msg = format_track_result(tracker, [SAMPLE_RESULT])
    assert "VIE→ATH June" in msg
    assert "VIE → ATH" in msg
    assert "2026-06-01" in msg
    assert "2026-06-08" in msg


def test_format_from_back_labels():
    tracker = _make_tracker()
    msg = format_track_result(tracker, [SAMPLE_RESULT])
    assert "FROM" in msg
    assert "BACK" in msg
    assert "FR1234" in msg
    assert "FR5678" in msg


def test_format_prices():
    tracker = _make_tracker()
    msg = format_track_result(tracker, [SAMPLE_RESULT])
    assert "89" in msg   # outbound
    assert "75" in msg   # return
    assert "164" in msg  # total


def test_format_trend_down():
    tracker = _make_tracker(price_history=[
        {"outbound_price": 110.0, "return_price": 100.0, "total_price": 210.0,
         "ts": "2026-03-04T08:00:00"}
    ])
    msg = format_track_result(tracker, [SAMPLE_RESULT])
    assert "↓" in msg


def test_format_trend_up():
    tracker = _make_tracker(price_history=[
        {"outbound_price": 60.0, "return_price": 50.0, "total_price": 110.0,
         "ts": "2026-03-04T08:00:00"}
    ])
    msg = format_track_result(tracker, [SAMPLE_RESULT])
    assert "↑" in msg


def test_format_no_trend_without_history():
    tracker = _make_tracker(price_history=[])
    msg = format_track_result(tracker, [SAMPLE_RESULT])
    assert "↑" not in msg
    assert "↓" not in msg


def test_format_shows_alternatives():
    alt = {**SAMPLE_RESULT, "outbound_flight": "FR9999", "total_price": 190.0}
    tracker = _make_tracker()
    msg = format_track_result(tracker, [SAMPLE_RESULT, alt])
    assert "Also" in msg
    assert "FR9999" in msg


def test_format_deal_flag():
    tracker = _make_tracker()
    result = {**SAMPLE_RESULT, "is_deal": True}
    msg = format_track_result(tracker, [result])
    assert "🔥" in msg
