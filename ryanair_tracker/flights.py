"""
Flight fetching using ryanair-py.
Fetches round-trips with departure time and duration filtering.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from ryanair import Ryanair
from ryanair.types import Trip


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
    min_nights: int = 1,
    max_nights: int = 14,
    dest_airport: str | None = None,
) -> list[dict]:
    """Fetch cheapest round-trips, iterating day-by-day from date_from to date_to.

    For each departure day d the return window is exactly [d+min_nights, d+max_nights],
    so a schedule with min=7, max=8 checks return on d+7 and d+8 only.
    """
    api = Ryanair(currency=currency)
    results = []

    time_from_str = time_from.strftime("%H:%M")
    time_to_str = time_to.strftime("%H:%M")

    if dest_airport:
        targets = [(None, dest_airport)]
    else:
        targets = [(cc, None) for cc in country_codes]

    for country_code, airport in targets:
        current = date_from
        while current <= date_to:
            # Clip window end to the requested range
            window_end = min(current + timedelta(days=6), date_to)
            try:
                trips: list[Trip] = api.get_cheapest_return_flights(
                    source_airport=origin,
                    date_from=current,
                    date_to=window_end,
                    # Return window covers departures across the whole window:
                    # earliest return = first day + min_nights
                    # latest return   = last day  + max_nights
                    return_date_from=current + timedelta(days=min_nights),
                    return_date_to=window_end + timedelta(days=max_nights),
                    destination_country=country_code,
                    destination_airport=airport,
                    outbound_departure_time_from=time_from_str,
                    outbound_departure_time_to=time_to_str,
                    inbound_departure_time_from=time_from_str,
                    inbound_departure_time_to=time_to_str,
                    max_price=int(max_price) if max_price else None,
                )
            except Exception:
                trips = []

            for trip in trips:
                dep_date = trip.outbound.departureTime.date()
                # Guard: skip if departure fell outside the requested range
                if dep_date < date_from or dep_date > date_to:
                    continue
                nights = (trip.inbound.departureTime.date() - dep_date).days
                if not (min_nights <= nights <= max_nights):
                    continue
                resolved_country = country_code or _iata_to_country(trip.outbound.destination)
                results.append(_trip_to_dict(trip, resolved_country, currency, nights))

            current += timedelta(days=7)

    # Deduplicate by (outbound_flight, return_flight)
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in results:
        key = (r["outbound_flight"], r["return_flight"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


def _trip_to_dict(trip: "Trip", country: str, currency: str, nights: int) -> dict:
    return {
        "outbound_flight": trip.outbound.flightNumber,
        "return_flight": trip.inbound.flightNumber,
        "origin": trip.outbound.origin,
        "destination": trip.outbound.destination,
        "country": country,
        "nights": nights,
        "outbound_depart": trip.outbound.departureTime.strftime("%Y-%m-%d %H:%M"),
        "return_depart": trip.inbound.departureTime.strftime("%Y-%m-%d %H:%M"),
        "outbound_price": float(trip.outbound.price),
        "return_price": float(trip.inbound.price),
        "total_price": float(trip.totalPrice),
        "currency": currency,
    }


_IATA_TO_COUNTRY: dict[str, str] = {
    "ATH": "GR", "SKG": "GR", "HER": "GR", "RHO": "GR", "CFU": "GR",
    "CHQ": "GR", "KGS": "GR", "ZTH": "GR", "JTR": "GR", "MJT": "GR",
    "PVK": "GR", "AOK": "GR", "EFL": "GR", "SMI": "GR", "JMK": "GR", "KLX": "GR",
    "FCO": "IT", "MXP": "IT", "BGY": "IT", "NAP": "IT", "VCE": "IT",
    "TSF": "IT", "BLQ": "IT", "PSA": "IT", "CTA": "IT", "PMO": "IT",
    "BRI": "IT", "SUF": "IT", "REG": "IT", "CAG": "IT", "AHO": "IT",
    "TRN": "IT", "VRN": "IT", "GOA": "IT", "BDS": "IT", "PSR": "IT",
    "RMI": "IT", "OLB": "IT", "QSR": "IT",
    "MAD": "ES", "BCN": "ES", "AGP": "ES", "ALC": "ES", "PMI": "ES",
    "IBZ": "ES", "SVQ": "ES", "VLC": "ES", "ACE": "ES", "TFS": "ES",
    "LPA": "ES", "FUE": "ES", "SDR": "ES", "BIO": "ES", "GRX": "ES",
}


def _iata_to_country(iata: str) -> str:
    return _IATA_TO_COUNTRY.get(iata, "??")
