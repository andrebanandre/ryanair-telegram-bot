"""Buchbinder car rental API client."""

from __future__ import annotations

from datetime import date

import requests

_BASE_URL = "https://kinsen-at.wheelsys.ms/default.aspx"
_HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": "https://buchbinder.co.at",
    "Referer": "https://buchbinder.co.at/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

_GEAR_MAP = {"A": "Auto", "M": "Manual"}


def fetch_prices(
    pickup: str,
    dropoff: str,
    pickup_date: date,
    dropoff_date: date,
    driver_age: int = 21,
) -> list[dict]:
    """Fetch available car rates from Buchbinder.

    Returns list sorted by total_price ascending.  Rates where
    Availability != "AVAILABLE" or StartingFrom <= 0 are excluded.
    """
    payload = {
        "reqData": {
            "DateFrom": pickup_date.strftime("%d/%m/%Y"),
            "DateTo": dropoff_date.strftime("%d/%m/%Y"),
            "TimeFrom": "12:00",
            "TimeTo": "12:00",
            "PickupStation": pickup,
            "ReturnStation": dropoff,
            "PickupPoint": "",
            "ReturnPoint": "",
            "CDP": "",
            "DriverAge": driver_age,
            "FlightNo": None,
            "QuoteId": None,
            "CarGroup": None,
            "Irn": None,
            "CustFirstName": None,
            "CustLastName": None,
            "CustEmail": None,
            "CustPhone": None,
            "CustAddress": None,
            "CustCity": None,
            "CustZip": None,
            "CustCountry": None,
            "CustLicenseNo": None,
            "CustLicenseCountry": None,
            "CustLicenseExpiry": None,
            "Remarks": None,
            "DownPayPercent": 0,
            "DownPayment": 0,
            "TotalRate": 0,
            "RentalRate": 0,
            "PaymentRef": None,
            "Uid": None,
            "RequestedFromURL": None,
            "Language": "de",
            "CurrencyCode": None,
            "Availability": None,
            "Options": None,
            "InvoiceName": None,
            "InvoiceTaxId": None,
            "InvoiceEmail": None,
            "InvoicePhone": None,
            "CCInfo": None,
            "PmtToken": None,
            "PmtTokenType": None,
            "DrvTaxId": None,
            "DriverDbId": 0,
            "GWSessionId": None,
        }
    }

    resp = requests.post(f"{_BASE_URL}/getPrice", json=payload, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()["d"]

    duration = data.get("Duration") or (dropoff_date - pickup_date).days
    if duration < 1:
        duration = 1

    currency = data.get("CurrencyCode", "EUR") or "EUR"
    rates = data.get("Rates") or []

    results: list[dict] = []
    for rate in rates:
        if rate.get("Availability") != "AVAILABLE":
            continue
        price = rate.get("StartingFrom", 0)
        if not price or price <= 0:
            continue

        category = rate.get("Category", "")
        model = rate.get("SampleModel", "") or ""
        label = f"{category} ({model})" if model else category
        gear_code = rate.get("GearType", "") or ""
        gear = _GEAR_MAP.get(gear_code, "")

        results.append(
            {
                "group_code": rate.get("GroupCode", ""),
                "category": category,
                "model": model,
                "label": label,
                "total_price": float(price),
                "per_day": float(price) / duration,
                "duration": duration,
                "unlimited_km": bool(rate.get("Unlimited", False)),
                "gear": gear,
                "currency": currency,
            }
        )

    results.sort(key=lambda r: r["total_price"])
    return results
