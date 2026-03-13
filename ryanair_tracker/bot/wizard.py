"""
/search ConversationHandler — 10-step flight search wizard.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .common import (
    AIRPORT,
    DATE_FROM,
    DATE_TO,
    DEPART_AFTER,
    DEPART_BEFORE,
    DEST,
    MAX_NIGHTS,
    MAX_PRICE,
    MIN_NIGHTS,
    ORIGIN,
    dest_keyboard,
    format_results,
    nights_keyboard,
    skip_keyboard,
    time_keyboard,
)
from ..flights import fetch_round_trips
from ..deals import evaluate_deal


async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "✈️ <b>Flight Search Wizard</b>\n\n"
        "Step 1/10: Enter your <b>origin airport</b> (3-letter IATA, e.g. <code>VIE</code>):",
        parse_mode="HTML",
    )
    return ORIGIN


async def received_origin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    if len(code) != 3 or not code.isalpha():
        await update.message.reply_text(
            "❌ Enter a valid 3-letter IATA code (e.g. <code>VIE</code>):",
            parse_mode="HTML",
        )
        return ORIGIN
    context.user_data["origin"] = code
    context.user_data["dest_selected"] = set()
    await update.message.reply_text(
        "Step 2/10: Select <b>destination countries</b> (tap to toggle, then Done ✅):",
        parse_mode="HTML",
        reply_markup=dest_keyboard(set()),
    )
    return DEST


async def toggle_dest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected: set[str] = context.user_data.setdefault("dest_selected", set())

    if query.data == "dest_skip_to_airport":
        # Bypass country selection entirely — go straight to IATA entry (required)
        context.user_data["dest_selected"] = set()
        await query.edit_message_text(
            "Step 3/10: Enter <b>destination airport</b> IATA (e.g. <code>ATH</code>, <code>RMI</code>):",
            parse_mode="HTML",
        )
        return AIRPORT
    elif query.data == "dest_done":
        if not selected:
            await query.edit_message_text(
                "⚠️ Select at least one country, type a 2-letter code, or use '✈️ Skip → enter airport IATA':",
                reply_markup=dest_keyboard(selected),
            )
            return DEST
        await query.edit_message_text(
            "Step 3/10: (Optional) Enter a specific <b>destination airport</b> IATA "
            "(e.g. <code>RMI</code>) to narrow the search, or skip for all airports:",
            parse_mode="HTML",
            reply_markup=skip_keyboard("skip_airport"),
        )
        return AIRPORT
    else:
        cc = query.data.replace("dest_", "")
        selected.discard(cc) if cc in selected else selected.add(cc)
        await query.edit_message_reply_markup(reply_markup=dest_keyboard(selected))
        return DEST


async def received_dest_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle free-text country/airport entry in the DEST step."""
    code = update.message.text.strip().upper()
    if len(code) == 3 and code.isalpha():
        # Treat as airport IATA — bypass country selection
        context.user_data["dest_airport"] = code
        context.user_data["dest_selected"] = set()
        return await _ask_date_from(update.message, context)
    elif len(code) == 2 and code.isalpha():
        selected: set[str] = context.user_data.setdefault("dest_selected", set())
        selected.add(code)
        await update.message.reply_text(
            f"Added <b>{code}</b>. Selected: {', '.join(sorted(selected))}\n"
            "Add more codes, toggle from the keyboard, or press Done ✅",
            parse_mode="HTML",
        )
        return DEST
    else:
        await update.message.reply_text(
            "❌ Enter a 2-letter country code (e.g. <code>FR</code>) "
            "or 3-letter airport IATA (e.g. <code>CDG</code>):",
            parse_mode="HTML",
        )
        return DEST


async def skip_airport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["dest_airport"] = None
    return await _ask_date_from(update.callback_query.message, context)


async def received_airport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    if len(code) != 3 or not code.isalpha():
        await update.message.reply_text(
            "❌ Enter a valid 3-letter IATA (e.g. <code>RMI</code>) or skip:",
            parse_mode="HTML",
            reply_markup=skip_keyboard("skip_airport"),
        )
        return AIRPORT
    context.user_data["dest_airport"] = code
    return await _ask_date_from(update.message, context)


async def _ask_date_from(msg, context: ContextTypes.DEFAULT_TYPE) -> int:
    await msg.reply_text(
        "Step 4/10: Enter <b>search start date</b> (YYYY-MM-DD) or skip for today:",
        parse_mode="HTML",
        reply_markup=skip_keyboard("skip_date_from"),
    )
    return DATE_FROM


async def skip_date_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["date_from"] = date.today()
    await update.callback_query.message.reply_text(
        "Step 5/10: Enter <b>search end date</b> (YYYY-MM-DD) or skip (today + 90 days):",
        parse_mode="HTML",
        reply_markup=skip_keyboard("skip_date_to"),
    )
    return DATE_TO


async def received_date_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["date_from"] = date.fromisoformat(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ Use YYYY-MM-DD format:", reply_markup=skip_keyboard("skip_date_from"),
        )
        return DATE_FROM
    await update.message.reply_text(
        "Step 5/10: Enter <b>search end date</b> (YYYY-MM-DD) or skip:",
        parse_mode="HTML",
        reply_markup=skip_keyboard("skip_date_to"),
    )
    return DATE_TO


async def skip_date_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    date_from = context.user_data.get("date_from", date.today())
    context.user_data["date_to"] = date_from + timedelta(days=90)
    await update.callback_query.message.reply_text(
        "Step 6/10: Select or enter <b>minimum nights</b>:",
        parse_mode="HTML",
        reply_markup=nights_keyboard(),
    )
    return MIN_NIGHTS


async def received_date_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["date_to"] = date.fromisoformat(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ Use YYYY-MM-DD format:", reply_markup=skip_keyboard("skip_date_to"),
        )
        return DATE_TO
    await update.message.reply_text(
        "Step 6/10: Select or enter <b>minimum nights</b>:",
        parse_mode="HTML",
        reply_markup=nights_keyboard(),
    )
    return MIN_NIGHTS


async def received_min_nights_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["min_nights"] = 1 if query.data == "nights_skip" else int(query.data.replace("nights_", ""))
    min_n = context.user_data["min_nights"]
    await query.message.reply_text(
        f"Step 7/10: Select or enter <b>maximum nights</b> (≥ {min_n}):",
        parse_mode="HTML",
        reply_markup=nights_keyboard(),
    )
    return MAX_NIGHTS


async def received_min_nights_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = int(update.message.text.strip())
        if not (1 <= val <= 30):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter 1–30:", reply_markup=nights_keyboard())
        return MIN_NIGHTS
    context.user_data["min_nights"] = val
    await update.message.reply_text(
        f"Step 7/10: Select or enter <b>maximum nights</b> (≥ {val}):",
        parse_mode="HTML",
        reply_markup=nights_keyboard(),
    )
    return MAX_NIGHTS


async def received_max_nights_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    min_n = context.user_data.get("min_nights", 1)
    if query.data == "nights_skip":
        context.user_data["max_nights"] = 14
    else:
        val = int(query.data.replace("nights_", ""))
        if val < min_n:
            await query.answer(f"Max nights must be ≥ {min_n}", show_alert=True)
            return MAX_NIGHTS
        context.user_data["max_nights"] = val
    await query.message.reply_text(
        "Step 8/10: Select <b>earliest departure time</b>:",
        parse_mode="HTML",
        reply_markup=time_keyboard(),
    )
    return DEPART_AFTER


async def received_max_nights_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    min_n = context.user_data.get("min_nights", 1)
    try:
        val = int(update.message.text.strip())
        if val < min_n:
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"❌ Enter ≥ {min_n}:", reply_markup=nights_keyboard())
        return MAX_NIGHTS
    context.user_data["max_nights"] = val
    await update.message.reply_text(
        "Step 8/10: Select <b>earliest departure time</b>:",
        parse_mode="HTML",
        reply_markup=time_keyboard(),
    )
    return DEPART_AFTER


async def received_depart_after(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["depart_after"] = query.data.replace("time_", "")
    await query.message.reply_text(
        "Step 9/10: Select <b>latest departure time</b>:",
        parse_mode="HTML",
        reply_markup=time_keyboard(),
    )
    return DEPART_BEFORE


async def received_depart_before(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["depart_before"] = query.data.replace("time_", "")
    await query.message.reply_text(
        "Step 10/10: Enter <b>max price</b> (EUR) or skip for no limit:",
        parse_mode="HTML",
        reply_markup=skip_keyboard("skip_max_price"),
    )
    return MAX_PRICE


async def skip_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["max_price"] = None
    return await _run_search(update, context)


async def received_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = float(update.message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Enter a positive number or skip:",
            reply_markup=skip_keyboard("skip_max_price"),
        )
        return MAX_PRICE
    context.user_data["max_price"] = val
    return await _run_search(update, context)


async def _run_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ud = context.user_data
    origin: str = ud["origin"]
    dest_selected: set[str] = ud.get("dest_selected", set())
    dest_airport: str | None = ud.get("dest_airport")
    date_from: date = ud.get("date_from", date.today())
    date_to: date = ud.get("date_to", date_from + timedelta(days=90))
    min_nights: int = ud.get("min_nights", 1)
    max_nights: int = ud.get("max_nights", 14)
    depart_after: str = ud.get("depart_after", "09:30")
    depart_before: str = ud.get("depart_before", "17:30")
    max_price: float | None = ud.get("max_price")
    dest_label = dest_airport or ", ".join(sorted(dest_selected))

    msg = update.callback_query.message if update.callback_query else update.message
    status_msg = await msg.reply_text("🔍 Searching…")

    try:
        from ..bot_history import load_history as load_bot_history, save_results as save_bot_results

        time_from = datetime.strptime(depart_after, "%H:%M").time()
        time_to = datetime.strptime(depart_before, "%H:%M").time()
        history = await asyncio.to_thread(load_bot_history)
        flights = await asyncio.to_thread(
            fetch_round_trips,
            origin=origin,
            country_codes=list(dest_selected),
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
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Search cancelled. Use /search to start again.")
    return ConversationHandler.END


def build_wizard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("search", start_search)],
        states={
            ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_origin)],
            DEST: [
                CallbackQueryHandler(toggle_dest, pattern="^dest_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_dest_text),
            ],
            AIRPORT: [
                CallbackQueryHandler(skip_airport, pattern="^skip_airport$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_airport),
            ],
            DATE_FROM: [
                CallbackQueryHandler(skip_date_from, pattern="^skip_date_from$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date_from),
            ],
            DATE_TO: [
                CallbackQueryHandler(skip_date_to, pattern="^skip_date_to$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date_to),
            ],
            MIN_NIGHTS: [
                CallbackQueryHandler(received_min_nights_cb, pattern="^nights_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_min_nights_text),
            ],
            MAX_NIGHTS: [
                CallbackQueryHandler(received_max_nights_cb, pattern="^nights_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_max_nights_text),
            ],
            DEPART_AFTER: [CallbackQueryHandler(received_depart_after, pattern="^time_")],
            DEPART_BEFORE: [CallbackQueryHandler(received_depart_before, pattern="^time_")],
            MAX_PRICE: [
                CallbackQueryHandler(skip_max_price, pattern="^skip_max_price$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_max_price),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
