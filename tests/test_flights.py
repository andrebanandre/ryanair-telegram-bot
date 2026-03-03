"""
Integration tests — real Ryanair API calls, no mocks.

Run with: pytest -m integration
Skipped in pre-commit (marked slow / network-dependent).
"""
import pytest
from datetime import date, time, timedelta

from ryanair_tracker.flights import fetch_round_trips


@pytest.mark.integration
def test_vie_to_greece_result_shape():
    """VIE→GR round-trips have all expected fields."""
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=90)
    results = fetch_round_trips(
        origin="VIE",
        country_codes=["GR"],
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=None,
        min_nights=7,
        max_nights=8,
    )
    required = {"origin", "destination", "outbound_flight", "return_flight",
                "outbound_price", "return_price", "total_price", "currency",
                "nights", "outbound_depart", "return_depart"}
    for r in results:
        assert required <= r.keys(), f"Missing fields in {r}"
        assert r["origin"] == "VIE"
        assert r["nights"] in (7, 8)
        assert r["total_price"] > 0
        assert r["outbound_price"] > 0
        assert r["return_price"] > 0


@pytest.mark.integration
def test_leg_prices_sum_to_total():
    """outbound_price + return_price ≈ total_price (within 1 EUR rounding)."""
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=75)
    results = fetch_round_trips(
        origin="VIE",
        country_codes=["IT"],
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=None,
        min_nights=5,
        max_nights=7,
    )
    for r in results:
        diff = abs(r["outbound_price"] + r["return_price"] - r["total_price"])
        assert diff < 1.0, f"Leg prices don't add up: {r}"


@pytest.mark.integration
def test_specific_airport_destination():
    """When dest_airport=RMI, all results must land at RMI."""
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=90)
    results = fetch_round_trips(
        origin="VIE",
        country_codes=[],
        dest_airport="RMI",
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=None,
        min_nights=7,
        max_nights=8,
    )
    for r in results:
        assert r["destination"] == "RMI"


@pytest.mark.integration
def test_nights_filter_respected():
    """All returned trips must have nights in [min_nights, max_nights]."""
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=90)
    results = fetch_round_trips(
        origin="VIE",
        country_codes=["ES"],
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=None,
        min_nights=7,
        max_nights=10,
    )
    for r in results:
        assert 7 <= r["nights"] <= 10, f"nights={r['nights']} out of range"


@pytest.mark.integration
def test_departure_date_within_window():
    """All departure dates must fall within [date_from, date_to]."""
    from datetime import datetime
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=75)
    results = fetch_round_trips(
        origin="VIE",
        country_codes=["GR"],
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=None,
        min_nights=7,
        max_nights=8,
    )
    for r in results:
        dep = datetime.strptime(r["outbound_depart"], "%Y-%m-%d %H:%M").date()
        assert date_from <= dep <= date_to, f"dep {dep} outside [{date_from}, {date_to}]"


@pytest.mark.integration
def test_max_price_filter():
    """Results must not exceed max_price."""
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=90)
    max_price = 400.0
    results = fetch_round_trips(
        origin="VIE",
        country_codes=["GR"],
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=max_price,
        min_nights=7,
        max_nights=8,
    )
    for r in results:
        assert r["total_price"] <= max_price


@pytest.mark.integration
def test_no_duplicates():
    """No duplicate (outbound_flight, return_flight) pairs."""
    date_from = date.today() + timedelta(days=60)
    date_to = date.today() + timedelta(days=90)
    results = fetch_round_trips(
        origin="VIE",
        country_codes=["GR", "IT"],
        date_from=date_from,
        date_to=date_to,
        time_from=time(6, 0),
        time_to=time(22, 0),
        max_price=None,
        min_nights=7,
        max_nights=8,
    )
    pairs = [(r["outbound_flight"], r["return_flight"]) for r in results]
    assert len(pairs) == len(set(pairs)), "Duplicate flight pairs found"
