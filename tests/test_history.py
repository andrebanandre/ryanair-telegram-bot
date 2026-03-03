"""Tests for bot_history: price persistence and trend calculation."""
from ryanair_tracker.bot_history import (
    load_history,
    save_results,
    trend_tag,
    leg_trend_tag,
    overall_trend,
)
from tests.conftest import SAMPLE_FLIGHT


TWO_ROUTES = [
    SAMPLE_FLIGHT,
    {**SAMPLE_FLIGHT, "destination": "CFU", "outbound_price": 95.0,
     "return_price": 80.0, "total_price": 175.0},
]


# ── save / load ────────────────────────────────────────────────────────────────

def test_save_creates_file(tmp_history):
    save_results([SAMPLE_FLIGHT], tmp_history)
    assert tmp_history.exists()


def test_save_and_load_round_trip(tmp_history):
    save_results([SAMPLE_FLIGHT], tmp_history)
    history = load_history(tmp_history)
    assert "VIE-ATH" in history
    assert len(history["VIE-ATH"]) == 1


def test_save_min_max_per_route(tmp_history):
    results = [
        SAMPLE_FLIGHT,  # total 164
        {**SAMPLE_FLIGHT, "outbound_price": 120.0, "return_price": 95.0, "total_price": 215.0},
    ]
    save_results(results, tmp_history)
    entry = load_history(tmp_history)["VIE-ATH"][0]
    assert entry["min_price"] == 164.0
    assert entry["max_price"] == 215.0


def test_save_leg_prices_from_cheapest_total(tmp_history):
    results = [
        SAMPLE_FLIGHT,  # total 164, out=89, ret=75  ← cheapest
        {**SAMPLE_FLIGHT, "outbound_price": 120.0, "return_price": 95.0, "total_price": 215.0},
    ]
    save_results(results, tmp_history)
    entry = load_history(tmp_history)["VIE-ATH"][0]
    assert entry["min_outbound"] == 89.0
    assert entry["min_return"] == 75.0


def test_save_multiple_routes(tmp_history):
    save_results(TWO_ROUTES, tmp_history)
    history = load_history(tmp_history)
    assert "VIE-ATH" in history
    assert "VIE-CFU" in history


def test_save_appends_across_runs(tmp_history):
    save_results([SAMPLE_FLIGHT], tmp_history)
    save_results([SAMPLE_FLIGHT], tmp_history)
    history = load_history(tmp_history)
    assert len(history["VIE-ATH"]) == 2


def test_load_missing_file_returns_empty(tmp_history):
    assert load_history(tmp_history) == {}


def test_load_corrupt_file_returns_empty(tmp_history):
    tmp_history.write_text("not json{{{")
    assert load_history(tmp_history) == {}


# ── trend_tag ─────────────────────────────────────────────────────────────────

def test_trend_tag_no_history():
    assert trend_tag(164.0, "VIE-ATH", {}) == ""


def test_trend_tag_price_dropped(tmp_history):
    prev = [{**SAMPLE_FLIGHT, "outbound_price": 110.0, "return_price": 100.0, "total_price": 210.0}]
    save_results(prev, tmp_history)
    history = load_history(tmp_history)
    tag = trend_tag(164.0, "VIE-ATH", history)
    assert "↓" in tag
    assert "%" in tag


def test_trend_tag_price_rose(tmp_history):
    prev = [{**SAMPLE_FLIGHT, "outbound_price": 60.0, "return_price": 50.0, "total_price": 110.0}]
    save_results(prev, tmp_history)
    history = load_history(tmp_history)
    tag = trend_tag(164.0, "VIE-ATH", history)
    assert "↑" in tag


def test_trend_tag_negligible_change_is_empty(tmp_history):
    # 164.5 is < 0.5% change from 164.0 → no tag
    save_results([SAMPLE_FLIGHT], tmp_history)
    history = load_history(tmp_history)
    assert trend_tag(164.5, "VIE-ATH", history) == ""


def test_trend_tag_unknown_route(tmp_history):
    save_results([SAMPLE_FLIGHT], tmp_history)
    history = load_history(tmp_history)
    assert trend_tag(164.0, "VIE-XXX", history) == ""


# ── leg_trend_tag ─────────────────────────────────────────────────────────────

def test_leg_trend_tag_no_history():
    assert leg_trend_tag(89.0, "VIE-ATH", "outbound", None) == ""
    assert leg_trend_tag(89.0, "VIE-ATH", "outbound", {}) == ""


def test_leg_trend_tag_outbound_rose(tmp_history):
    save_results([SAMPLE_FLIGHT], tmp_history)  # min_outbound=89
    history = load_history(tmp_history)
    tag = leg_trend_tag(110.0, "VIE-ATH", "outbound", history)
    assert "↑" in tag


def test_leg_trend_tag_return_dropped(tmp_history):
    prev = [{**SAMPLE_FLIGHT, "return_price": 100.0, "total_price": 189.0}]
    save_results(prev, tmp_history)  # min_return=100
    history = load_history(tmp_history)
    tag = leg_trend_tag(75.0, "VIE-ATH", "return", history)
    assert "↓" in tag


def test_leg_trend_tag_unknown_route():
    assert leg_trend_tag(89.0, "VIE-ZZZ", "outbound", {"VIE-ATH": []}) == ""


# ── overall_trend ─────────────────────────────────────────────────────────────

def test_overall_trend_no_history():
    assert overall_trend(164.0, [SAMPLE_FLIGHT], {}) == ""


def test_overall_trend_dropped(tmp_history):
    prev = [{**SAMPLE_FLIGHT, "total_price": 210.0, "outbound_price": 110.0, "return_price": 100.0}]
    save_results(prev, tmp_history)
    history = load_history(tmp_history)
    ot = overall_trend(164.0, [SAMPLE_FLIGHT], history)
    assert "↓" in ot
    assert "vs prev" in ot


def test_overall_trend_rose(tmp_history):
    prev = [{**SAMPLE_FLIGHT, "total_price": 110.0, "outbound_price": 60.0, "return_price": 50.0}]
    save_results(prev, tmp_history)
    history = load_history(tmp_history)
    ot = overall_trend(164.0, [SAMPLE_FLIGHT], history)
    assert "↑" in ot
