"""
Flight fetching using ryanair-py.
Fetches round-trips with departure time filtering.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from ryanair import Ryanair
from ryanair.types import Trip


# Map country codes → Ryanair API country names
COUNTRY_MAP = {
    "GR": "Greece",
    "IT": "Italy",
    "ES": "Spain",
    "PT": "Portugal",
    "HR": "Croatia",
    "FR": "France",
    "DE": "Germany",
}


def fetch_round_trips(
    origin: str,
    country_codes: list[str],
    date_from: date,
    date_to: date,
    time_from: time,
    time_to: time,
    max_price: float | None,
    currency: str = "EUR",
) -> list[dict]:
    """Fetch cheapest round-trips from origin to given countries, filtered by time window."""

    api = Ryanair(currency=currency)
    results = []

    # ryanair-py searches day-by-day, so we iterate over the date range
    current = date_from
    while current <= date_to:
        try:
            trips: list[Trip] = api.get_cheapest_return_flights(
                source_airport=origin,
                date_from=current,
                date_to=current + timedelta(days=7),       # outbound window
                return_date_from=current + timedelta(days=2),
                return_date_to=current + timedelta(days=14),
                max_price=max_price,
            )
        except Exception:
            trips = []

        for trip in trips:
            # Filter by country
            dest_country = _resolve_country(trip.outbound.destination, country_codes)
            if dest_country is None:
                continue

            # Filter outbound departure time
            out_time = trip.outbound.departureTime.time()
            ret_time = trip.inbound.departureTime.time()
            if not (time_from <= out_time <= time_to):
                continue
            if not (time_from <= ret_time <= time_to):
                continue

            results.append(_trip_to_dict(trip, dest_country, currency))

        current += timedelta(days=7)

    # Deduplicate by (outbound_flight, return_flight)
    seen = set()
    unique = []
    for r in results:
        key = (r["outbound_flight"], r["return_flight"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


def _trip_to_dict(trip: "Trip", country: str, currency: str) -> dict:
    return {
        "outbound_flight": trip.outbound.flightNumber,
        "return_flight": trip.inbound.flightNumber,
        "origin": trip.outbound.origin,
        "destination": trip.outbound.destination,
        "country": country,
        "outbound_depart": trip.outbound.departureTime.strftime("%Y-%m-%d %H:%M"),
        "outbound_arrive": trip.outbound.arrivalTime.strftime("%Y-%m-%d %H:%M"),
        "return_depart": trip.inbound.departureTime.strftime("%Y-%m-%d %H:%M"),
        "return_arrive": trip.inbound.arrivalTime.strftime("%Y-%m-%d %H:%M"),
        "outbound_price": float(trip.outbound.price),
        "return_price": float(trip.inbound.price),
        "total_price": float(trip.totalPrice),
        "currency": currency,
    }


def _resolve_country(iata: str, country_codes: list[str]) -> str | None:
    """
    Try to match the destination IATA code to one of the requested countries.
    ryanair-py Trip objects don't directly expose country, so we rely on
    a hardcoded IATA prefix map for common Ryanair destinations.
    """
    # Country prefix hints — extend as needed
    IATA_TO_COUNTRY: dict[str, str] = {
        # Greece
        "ATH": "GR", "SKG": "GR", "HER": "GR", "RHO": "GR", "CFU": "GR",
        "CHQ": "GR", "KGS": "GR", "ZTH": "GR", "JTR": "GR", "MJT": "GR",
        "PVK": "GR", "AOK": "GR", "EFL": "GR", "SMI": "GR",
        # Italy
        "FCO": "IT", "MXP": "IT", "BGY": "IT", "NAP": "IT", "VCE": "IT",
        "TSF": "IT", "BLQ": "IT", "PSA": "IT", "CTA": "IT", "PMO": "IT",
        "BRI": "IT", "SUF": "IT", "REG": "IT", "CAG": "IT", "AHO": "IT",
        "TRN": "IT", "VRN": "IT", "GOA": "IT", "BDS": "IT", "PSR": "IT",
        # Spain
        "MAD": "ES", "BCN": "ES", "AGP": "ES", "ALC": "ES", "PMI": "ES",
        "IBZ": "ES", "SVQ": "ES", "VLC": "ES", "ACE": "ES", "TFS": "ES",
        "LPA": "ES", "FUE": "ES", "SDR": "ES", "BIO": "ES", "GRX": "ES",
        "MRS": "ES", "ZAZ": "ES", "REU": "ES",
    }

    country = IATA_TO_COUNTRY.get(iata)
    if country and country in country_codes:
        return country
    return None
