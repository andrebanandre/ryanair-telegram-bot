"""Bot search history — JSON price history per route for trend display."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DEFAULT_HISTORY_FILE = Path("./data/bot_history.json")
MAX_ENTRIES_PER_ROUTE = 60


def load_history(path: Path = DEFAULT_HISTORY_FILE) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_results(results: list[dict], path: Path = DEFAULT_HISTORY_FILE) -> None:
    """Persist min/max price per route from a search run, including per-leg prices."""
    if not results:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(path)
    ts = datetime.now().isoformat(timespec="seconds")

    # Aggregate per route: track legs of the cheapest total trip
    routes: dict[str, dict] = {}
    for r in results:
        key = f"{r['origin']}-{r['destination']}"
        total = r["total_price"]
        out_p = r.get("outbound_price", 0.0)
        ret_p = r.get("return_price", 0.0)
        if key not in routes:
            routes[key] = {"min": total, "max": total, "min_out": out_p, "min_ret": ret_p}
        else:
            if total < routes[key]["min"]:
                routes[key]["min"] = total
                routes[key]["min_out"] = out_p
                routes[key]["min_ret"] = ret_p
            routes[key]["max"] = max(routes[key]["max"], total)

    for key, prices in routes.items():
        entries = history.setdefault(key, [])
        entries.append({
            "min_price": prices["min"],
            "max_price": prices["max"],
            "min_outbound": prices["min_out"],
            "min_return": prices["min_ret"],
            "ts": ts,
        })
        history[key] = entries[-MAX_ENTRIES_PER_ROUTE:]

    path.write_text(json.dumps(history, indent=2))


def _prev_entry(route_key: str, history: dict[str, list[dict]]) -> dict | None:
    entries = history.get(route_key, [])
    return entries[-1] if entries else None


def trend_tag(current_price: float, route_key: str, history: dict[str, list[dict]]) -> str:
    """↑/↓% vs last recorded min price for this route."""
    entry = _prev_entry(route_key, history)
    if entry is None:
        return ""
    # backwards compat: old entries may only have "price"
    prev = entry.get("min_price") or entry.get("price")
    if not prev or prev == 0:
        return ""
    pct = (current_price - prev) / prev * 100
    if abs(pct) < 0.5:
        return ""
    return f" {'↑' if pct > 0 else '↓'}{abs(pct):.0f}%"


def leg_trend_tag(
    current_price: float,
    route_key: str,
    leg: str,  # "outbound" or "return"
    history: dict[str, list[dict]] | None,
) -> str:
    """↑/↓% for a single leg vs last recorded min for that leg."""
    if not history:
        return ""
    entry = _prev_entry(route_key, history)
    if entry is None:
        return ""
    prev = entry.get(f"min_{leg}")  # "min_outbound" or "min_return"
    if not prev or prev == 0:
        return ""
    pct = (current_price - prev) / prev * 100
    if abs(pct) < 0.5:
        return ""
    return f" {'↑' if pct > 0 else '↓'}{abs(pct):.0f}%"


def overall_trend(
    current_min: float,
    results: list[dict],
    history: dict[str, list[dict]],
) -> str:
    """↑/↓% vs best (lowest) previously recorded min price across all result routes."""
    prev_mins = []
    for r in results:
        key = f"{r['origin']}-{r['destination']}"
        entry = _prev_entry(key, history)
        if entry:
            p = entry.get("min_price") or entry.get("price")
            if p:
                prev_mins.append(p)
    if not prev_mins:
        return ""
    prev_best = min(prev_mins)
    pct = (current_min - prev_best) / prev_best * 100
    if abs(pct) < 0.5:
        return ""
    return f" {'↑' if pct > 0 else '↓'}{abs(pct):.0f}% vs prev"
