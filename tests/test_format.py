"""Tests for result formatting and deal evaluation."""
from ryanair_tracker.bot.common import format_results
from ryanair_tracker.deals import evaluate_deal
from tests.conftest import SAMPLE_FLIGHT


TWO_RESULTS = [
    SAMPLE_FLIGHT,
    {**SAMPLE_FLIGHT, "destination": "CFU", "outbound_flight": "FR2222",
     "return_flight": "FR3333", "outbound_price": 95.0,
     "return_price": 80.0, "total_price": 175.0},
]


# ── format_results ────────────────────────────────────────────────────────────

def test_empty_results():
    msg = format_results([], 0, "VIE", "Greece")
    assert "No flights found" in msg


def test_header_contains_route(tmp_history):
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece")
    assert "VIE" in msg
    assert "Greece" in msg


def test_header_shows_result_count():
    msg = format_results(TWO_RESULTS, 2, "VIE", "Greece")
    assert "2 results" in msg


def test_header_shows_price_range():
    msg = format_results(TWO_RESULTS, 2, "VIE", "Greece")
    assert "164" in msg  # min price
    assert "175" in msg  # max price
    assert "EUR" in msg


def test_from_back_labels_present():
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece")
    assert "FROM" in msg
    assert "BACK" in msg


def test_flight_numbers_present():
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece")
    assert "FR1234" in msg
    assert "FR5678" in msg


def test_route_directions():
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece")
    assert "VIE→ATH" in msg
    assert "ATH→VIE" in msg


def test_nights_shown():
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece")
    assert "7n" in msg


def test_leg_prices_shown():
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece")
    assert "89" in msg   # outbound price
    assert "75" in msg   # return price
    assert "164" in msg  # total price


def test_deal_flag():
    result = {**SAMPLE_FLIGHT, "is_deal": True}
    msg = format_results([result], 1, "VIE", "Greece")
    assert "🔥" in msg


def test_no_deal_flag_when_not_deal():
    result = {**SAMPLE_FLIGHT, "is_deal": False}
    msg = format_results([result], 1, "VIE", "Greece")
    assert "🔥" not in msg


def test_sorted_cheapest_first():
    msg = format_results(TWO_RESULTS, 2, "VIE", "Greece")
    # FR1234 (164 EUR) must appear before FR2222 (175 EUR)
    assert msg.index("FR1234") < msg.index("FR2222")


def test_trend_shown_when_history_provided(tmp_history):
    from ryanair_tracker.bot_history import save_results, load_history
    prev = [{**SAMPLE_FLIGHT, "total_price": 210.0, "outbound_price": 110.0, "return_price": 100.0}]
    save_results(prev, tmp_history)
    history = load_history(tmp_history)
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece", history)
    assert "↓" in msg


def test_no_trend_without_history():
    msg = format_results([SAMPLE_FLIGHT], 1, "VIE", "Greece", history=None)
    assert "↑" not in msg
    assert "↓" not in msg


# ── evaluate_deal ─────────────────────────────────────────────────────────────

def test_evaluate_deal_no_history():
    result = evaluate_deal(SAMPLE_FLIGHT, {}, threshold_pct=20.0)
    assert result["is_deal"] is False
    assert result["savings_pct"] == 0.0
    assert result["historical_avg"] is None


def test_evaluate_deal_detected():
    history = {"VIE-ATH": [250.0, 260.0, 240.0]}
    result = evaluate_deal(SAMPLE_FLIGHT, history, threshold_pct=20.0)
    assert result["is_deal"] is True
    assert result["savings_pct"] > 20.0


def test_evaluate_deal_not_triggered():
    history = {"VIE-ATH": [160.0, 170.0]}
    result = evaluate_deal(SAMPLE_FLIGHT, history, threshold_pct=20.0)
    assert result["is_deal"] is False


def test_evaluate_deal_passthrough_fields():
    result = evaluate_deal(SAMPLE_FLIGHT, {}, threshold_pct=20.0)
    assert result["origin"] == "VIE"
    assert result["total_price"] == 164.0
    assert result["nights"] == 7


def test_evaluate_deal_needs_at_least_two_history_points():
    # Single data point → not enough → no deal detected
    history = {"VIE-ATH": [300.0]}
    result = evaluate_deal(SAMPLE_FLIGHT, history, threshold_pct=20.0)
    assert result["is_deal"] is False
