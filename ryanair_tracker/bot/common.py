"""Shared state constants, keyboard builders, and result formatters."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Wizard conversation state indices
ORIGIN, DEST, AIRPORT, DATE_FROM, DATE_TO, MIN_NIGHTS, MAX_NIGHTS, DEPART_AFTER, DEPART_BEFORE, MAX_PRICE = range(10)

DEST_COUNTRIES = ["GR", "IT", "ES", "PT", "HR"]

COUNTRY_NAMES = {
    "GR": "Greece",
    "IT": "Italy",
    "ES": "Spain",
    "PT": "Portugal",
    "HR": "Croatia",
}


def dest_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for cc in DEST_COUNTRIES:
        label = f"{'✅ ' if cc in selected else ''}{cc}"
        row.append(InlineKeyboardButton(label, callback_data=f"dest_{cc}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Done ✅", callback_data="dest_done")])
    return InlineKeyboardMarkup(buttons)


def time_keyboard() -> InlineKeyboardMarkup:
    times = [
        "06:00", "07:00", "08:00", "09:00",
        "10:00", "11:00", "12:00", "13:00",
        "14:00", "15:00", "16:00", "17:00",
        "18:00", "19:00", "20:00", "22:00",
    ]
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for t in times:
        row.append(InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def nights_keyboard() -> InlineKeyboardMarkup:
    presets = [3, 5, 7, 8, 10, 14]
    row = [InlineKeyboardButton(str(n), callback_data=f"nights_{n}") for n in presets]
    buttons = [row[:3], row[3:], [InlineKeyboardButton("Skip (any)", callback_data="nights_skip")]]
    return InlineKeyboardMarkup(buttons)


def skip_keyboard(cb_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Skip ⏭", callback_data=cb_data)]])


def format_results(
    results: list[dict],
    total: int,
    origin: str,
    dest_label: str,
    history: dict[str, list[dict]] | None = None,
) -> str:
    """Format results as Telegram HTML.

    Header shows overall price range (min–max) and % trend vs previous run.
    Each line shows individual flight with per-route trend tag.
    """
    if not results:
        return f"<b>No flights found</b> from {origin} to {dest_label}."

    from ..bot_history import trend_tag, overall_trend as calc_overall_trend

    shown = sorted(results, key=lambda x: x["total_price"])[:15]
    prices = [r["total_price"] for r in results]
    min_p, max_p = min(prices), max(prices)
    currency = results[0]["currency"]

    if history:
        ot = calc_overall_trend(min_p, results, history)
    else:
        ot = ""

    lines = [
        f"<b>Flights {origin} → {dest_label}</b>  ({total} results)\n"
        f"Price: <b>{min_p:.0f}–{max_p:.0f} {currency}</b>{ot}\n"
    ]
    for r in shown:
        out_dt = r["outbound_depart"][5:]  # MM-DD HH:MM
        ret_dt = r["return_depart"][5:]
        route_key = f"{r['origin']}-{r['destination']}"
        trend = trend_tag(r["total_price"], route_key, history) if history else ""
        deal = " 🔥" if r.get("is_deal") else ""
        lines.append(
            f"<b>{r['outbound_flight']}</b> {out_dt} → {r['destination']}, "
            f"back {ret_dt} ({r['nights']}n) "
            f"<b>{r['total_price']:.0f} {currency}</b>{trend}{deal}"
        )
    return "\n".join(lines)


def build_cli_message(deals: list[dict], total: int) -> str:
    if not deals:
        return f"<b>Ryanair Tracker:</b> {total} flights found, no deals this run."
    lines = [f"<b>🔥 {len(deals)} deal(s) found!</b> ({total} flights searched)\n"]
    for r in sorted(deals, key=lambda x: x["total_price"])[:10]:
        out_dt = r["outbound_depart"][5:]
        ret_dt = r["return_depart"][5:]
        lines.append(
            f"<b>{r['outbound_flight']}</b> {out_dt} → {r['destination']}, "
            f"back {ret_dt} ({r['nights']}n) "
            f"<b>{r['total_price']:.0f} {r['currency']}</b>"
        )
    return "\n".join(lines)
