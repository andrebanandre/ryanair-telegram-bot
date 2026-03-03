"""Shared fixtures for all test modules."""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_history(tmp_path) -> Path:
    return tmp_path / "bot_history.json"


@pytest.fixture
def tmp_schedules(tmp_path) -> Path:
    return tmp_path / "schedules.json"


SAMPLE_FLIGHT = {
    "origin": "VIE",
    "destination": "ATH",
    "outbound_flight": "FR1234",
    "return_flight": "FR5678",
    "outbound_price": 89.0,
    "return_price": 75.0,
    "total_price": 164.0,
    "currency": "EUR",
    "nights": 7,
    "outbound_depart": "2026-05-01 06:30",
    "return_depart": "2026-05-08 10:15",
    "is_deal": False,
}

SAMPLE_SCHEDULE = {
    "chat_id": 12345,
    "name": "Test VIE→GR",
    "origin": "VIE",
    "country_codes": ["GR"],
    "dest_airport": None,
    "date_from": "2026-05-01",
    "date_to": "2026-08-31",
    "min_nights": 7,
    "max_nights": 8,
    "depart_after": "06:00",
    "depart_before": "18:00",
    "max_price": None,
    "days": "daily",
    "hour": 8,
    "minute": 0,
}
