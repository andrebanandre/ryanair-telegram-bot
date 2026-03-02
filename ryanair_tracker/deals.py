"""
Deal evaluation: compare current price against historical average for the route.
"""

from __future__ import annotations

import statistics


def evaluate_deal(
    flight: dict,
    history: dict[str, list[float]],
    threshold_pct: float,
) -> dict:
    """
    Enrich a flight dict with deal metadata:
      - historical_avg: average price seen for this route
      - savings_pct: how much cheaper vs average
      - is_deal: True if savings_pct >= threshold_pct
    """
    route = f"{flight['origin']}-{flight['destination']}"
    past_prices = history.get(route, [])

    if len(past_prices) >= 2:
        avg = statistics.mean(past_prices)
        savings_pct = (avg - flight["total_price"]) / avg * 100
    else:
        avg = None
        savings_pct = 0.0

    return {
        **flight,
        "historical_avg": avg,
        "savings_pct": round(savings_pct, 1),
        "is_deal": savings_pct >= threshold_pct,
    }
