"""
/find ORIGIN DEST DATE_FROM DATE_TO [MIN_NIGHTS [MAX_NIGHTS [MAX_PRICE]]]

DEST: comma-separated 2-char country codes (GR,IT,ES) or a single 3-char airport (RMI).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from telegram import Update
from telegram.ext import ContextTypes

from .common import format_results
from ..flights import fetch_round_trips
from ..deals import evaluate_deal

USAGE = (
    "/find ORIGIN DEST DATE_FROM DATE_TO [MIN_NIGHTS [MAX_NIGHTS [MAX_PRICE]]]\n\n"
    "DEST: comma-separated country codes (GR,IT) or single airport (RMI)\n\n"
    "Examples:\n"
    "<code>/find VIE GR 2026-05-01 2026-06-30 7 8</code>\n"
    "<code>/find VIE GR,IT,ES 2026-05-01 2026-07-31 5 10 300</code>\n"
    "<code>/find VIE RMI 2026-06-01 2026-08-31</code>"
)


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 4:
        await update.message.reply_text(f"Usage:\n{USAGE}", parse_mode="HTML")
        return

    origin = args[0].upper()
    dest_arg = args[1].upper()
    date_from_str = args[2]
    date_to_str = args[3]
    min_nights = int(args[4]) if len(args) > 4 else 1
    max_nights = int(args[5]) if len(args) > 5 else 14
    max_price = float(args[6]) if len(args) > 6 else None

    try:
        date_from = date.fromisoformat(date_from_str)
        date_to = date.fromisoformat(date_to_str)
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Use YYYY-MM-DD.")
        return

    # 2-char segments → country codes; single 3-char → airport IATA
    if "," in dest_arg or len(dest_arg) == 2:
        country_codes = [c.strip() for c in dest_arg.split(",")]
        dest_airport = None
    else:
        country_codes = []
        dest_airport = dest_arg
    dest_label = dest_arg

    status_msg = await update.message.reply_text("🔍 Searching…")

    try:
        from ..bot_history import load_history as load_bot_history, save_results as save_bot_results

        time_from = datetime.strptime("09:30", "%H:%M").time()
        time_to = datetime.strptime("17:30", "%H:%M").time()

        history = await asyncio.to_thread(load_bot_history)
        flights = await asyncio.to_thread(
            fetch_round_trips,
            origin=origin,
            country_codes=country_codes,
            dest_airport=dest_airport,
            date_from=date_from,
            date_to=date_to,
            time_from=time_from,
            time_to=time_to,
            max_price=max_price,
            min_nights=min_nights,
            max_nights=max_nights,
        )
        results = [evaluate_deal(f, {}, 20.0) for f in flights]
        text = format_results(results, len(results), origin, dest_label, history)
        await asyncio.to_thread(save_bot_results, results)
    except Exception as e:
        text = f"❌ Search failed: {e}"

    await status_msg.edit_text(text, parse_mode="HTML")
