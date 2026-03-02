"""
/schedules — manage scheduled flight searches.

13-step wizard:
  name → run-time → days → origin → dest → airport (optional)
  → date-from (YYYY-MM-DD) → date-to (YYYY-MM-DD)
  → min-nights → max-nights → depart-after → depart-before → max-price
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .common import dest_keyboard, format_results, nights_keyboard, time_keyboard, skip_keyboard
from ..flights import fetch_round_trips
from ..deals import evaluate_deal
from ..schedules import (
    add_schedule, delete_schedule, get_schedule, get_user_schedules, update_schedule,
)

# ── States ────────────────────────────────────────────────────────────────────
(
    SCHED_MENU,
    SCHED_NAME,
    SCHED_RUN_TIME,
    SCHED_DAYS,
    SCHED_ORIGIN,
    SCHED_DEST,
    SCHED_AIRPORT,
    SCHED_DATE_FROM,
    SCHED_DATE_TO,
    SCHED_MIN_NIGHTS,
    SCHED_MAX_NIGHTS,
    SCHED_DEPART_AFTER,
    SCHED_DEPART_BEFORE,
    SCHED_MAX_PRICE,
    SCHED_DELETE_CONFIRM,
) = range(15)

DAYS_LABELS = {"daily": "Every day", "weekdays": "Mon–Fri", "weekends": "Sat–Sun"}

scheduler = AsyncIOScheduler()
_schedules_file: Path = Path("./schedules.json")

# ── Keyboards ─────────────────────────────────────────────────────────────────

def _run_time_keyboard() -> InlineKeyboardMarkup:
    times = [
        "03:00", "04:00", "05:00", "06:00",
        "07:00", "08:00", "09:00", "10:00",
        "11:00", "12:00", "13:00", "14:00",
        "15:00", "16:00", "17:00", "18:00",
        "19:00", "20:00", "22:00",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for t in times:
        row.append(InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _menu_keyboard(schedules: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in schedules:
        time_label = f"{s['hour']:02d}:{s['minute']:02d}"
        days_label = DAYS_LABELS.get(s["days"], s["days"])
        dest = s.get("dest_airport") or ", ".join(s.get("country_codes") or ["?"])
        date_from = s.get("date_from", "?")
        date_to = s.get("date_to", "?")
        rows.append([InlineKeyboardButton(
            f"⏰ {s['name']}  {s.get('origin','?')}→{dest}  "
            f"{days_label} {time_label}  {date_from}–{date_to}",
            callback_data="sched_noop",
        )])
        rows.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"sched_edit_{s['id']}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"sched_delete_{s['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Add new schedule", callback_data="sched_add")])
    return InlineKeyboardMarkup(rows)


def _days_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Every day", callback_data="days_daily"),
        InlineKeyboardButton("Mon–Fri", callback_data="days_weekdays"),
        InlineKeyboardButton("Sat–Sun", callback_data="days_weekends"),
    ]])


def _with_keep(kb: InlineKeyboardMarkup, label: str) -> InlineKeyboardMarkup:
    rows = list(kb.inline_keyboard) + [
        [InlineKeyboardButton(f"Keep: {label}", callback_data="sched_keep")]
    ]
    return InlineKeyboardMarkup(rows)


def _keep_only(label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Keep: {label}", callback_data="sched_keep")
    ]])

# ── Helpers ───────────────────────────────────────────────────────────────────

def _editing(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(ctx.user_data.get("sched_editing_id"))


def _draft(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    return ctx.user_data.setdefault("sched_draft", {})


def _clear_draft(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.user_data.pop("sched_draft", None)
    ctx.user_data.pop("sched_editing_id", None)
    ctx.user_data.pop("sched_dest_selected", None)


async def _show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, new_msg: bool = False) -> int:
    chat_id = update.effective_chat.id
    schedules = get_user_schedules(chat_id, _schedules_file)
    text = (
        f"📅 <b>Your Schedules</b> ({len(schedules)})\n\nTap Edit or Delete on any entry:"
        if schedules else
        "📅 <b>No schedules yet.</b>\nAdd one to get automatic flight deal alerts!"
    )
    kb = _menu_keyboard(schedules)
    if update.callback_query and not new_msg:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            return SCHED_MENU
        except Exception:
            pass
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    return SCHED_MENU


# ── Entry ─────────────────────────────────────────────────────────────────────

async def show_schedules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    ctx.user_data.pop("sched_delete_id", None)
    return await _show_menu(update, ctx)


# ── Menu callbacks ────────────────────────────────────────────────────────────

async def handle_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return SCHED_MENU


async def handle_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    ctx.user_data["sched_draft"] = {"chat_id": update.effective_chat.id}
    ctx.user_data.pop("sched_editing_id", None)
    ctx.user_data["sched_dest_selected"] = set()
    await update.callback_query.message.reply_text(
        "➕ <b>New Schedule</b>\n\nStep 1/13: Enter a <b>name</b>:",
        parse_mode="HTML",
    )
    return SCHED_NAME


async def handle_edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    sched_id = update.callback_query.data.replace("sched_edit_", "")
    s = get_schedule(sched_id, _schedules_file)
    if not s:
        await update.callback_query.answer("Schedule not found.", show_alert=True)
        return await _show_menu(update, ctx)
    ctx.user_data["sched_editing_id"] = sched_id
    ctx.user_data["sched_draft"] = dict(s)
    ctx.user_data["sched_dest_selected"] = set(s.get("country_codes") or [])
    await update.callback_query.message.reply_text(
        f"✏️ <b>Editing: {s['name']}</b>\n\nStep 1/13: New <b>name</b> or keep:",
        parse_mode="HTML",
        reply_markup=_keep_only(s["name"]),
    )
    return SCHED_NAME


async def handle_delete_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    sched_id = update.callback_query.data.replace("sched_delete_", "")
    s = get_schedule(sched_id, _schedules_file)
    if not s:
        return await _show_menu(update, ctx)
    ctx.user_data["sched_delete_id"] = sched_id
    await update.callback_query.edit_message_text(
        f"🗑️ Delete <b>{s['name']}</b>?\nThis cannot be undone.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, delete", callback_data="sched_del_yes"),
            InlineKeyboardButton("❌ No, keep", callback_data="sched_del_no"),
        ]]),
    )
    return SCHED_DELETE_CONFIRM


# ── Delete confirm ────────────────────────────────────────────────────────────

async def delete_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    sched_id = ctx.user_data.pop("sched_delete_id", None)
    if sched_id:
        delete_schedule(sched_id, _schedules_file)
        _remove_job(sched_id)
    return await _show_menu(update, ctx)


async def delete_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _show_menu(update, ctx)


# ── Step 1: Name ──────────────────────────────────────────────────────────────

async def received_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    else:
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("Please enter a name:")
            return SCHED_NAME
        _draft(ctx)["name"] = name

    kb = _run_time_keyboard()
    if _editing(ctx):
        d = _draft(ctx)
        kb = _with_keep(kb, f"{d.get('hour', 8):02d}:{d.get('minute', 0):02d}")
    await update.effective_message.reply_text(
        "Step 2/13: Select <b>run time</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_RUN_TIME


# ── Step 2: Run time ──────────────────────────────────────────────────────────

async def received_run_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data != "sched_keep":
        h, m = map(int, query.data.replace("time_", "").split(":"))
        _draft(ctx)["hour"] = h
        _draft(ctx)["minute"] = m

    kb = _days_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, DAYS_LABELS.get(_draft(ctx).get("days", "daily"), "Every day"))
    await query.message.reply_text(
        "Step 3/13: Select <b>which days</b> to run:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_DAYS


# ── Step 3: Days ──────────────────────────────────────────────────────────────

async def received_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data != "sched_keep":
        mapping = {"days_daily": "daily", "days_weekdays": "weekdays", "days_weekends": "weekends"}
        _draft(ctx)["days"] = mapping.get(query.data, "daily")

    text = "Step 4/13: Enter <b>origin airport</b> IATA (e.g. <code>VIE</code>):"
    if _editing(ctx):
        await query.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("origin", "VIE")),
        )
    else:
        await query.message.reply_text(text, parse_mode="HTML")
    return SCHED_ORIGIN


# ── Step 4: Origin ────────────────────────────────────────────────────────────

async def received_origin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    else:
        code = update.message.text.strip().upper()
        if len(code) != 3 or not code.isalpha():
            await update.message.reply_text(
                "❌ Enter a valid 3-letter IATA (e.g. <code>VIE</code>):",
                parse_mode="HTML",
            )
            return SCHED_ORIGIN
        _draft(ctx)["origin"] = code

    if _editing(ctx) and not ctx.user_data.get("sched_dest_selected"):
        ctx.user_data["sched_dest_selected"] = set(_draft(ctx).get("country_codes") or [])

    selected: set[str] = ctx.user_data.get("sched_dest_selected", set())
    await update.effective_message.reply_text(
        "Step 5/13: Select <b>destination countries</b> (toggle, then Done ✅):",
        parse_mode="HTML",
        reply_markup=dest_keyboard(selected),
    )
    return SCHED_DEST


# ── Step 5: Destination ───────────────────────────────────────────────────────

async def toggle_dest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected: set[str] = ctx.user_data.setdefault("sched_dest_selected", set())

    if query.data == "dest_done":
        if not selected:
            await query.edit_message_text(
                "⚠️ Select at least one destination:",
                reply_markup=dest_keyboard(selected),
            )
            return SCHED_DEST
        _draft(ctx)["country_codes"] = list(selected)

        cur_airport = _draft(ctx).get("dest_airport")
        kb = skip_keyboard("sched_skip_airport")
        if _editing(ctx) and cur_airport:
            kb = _with_keep(kb.inline_keyboard[0][0].callback_data and kb or kb, cur_airport)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Keep: {cur_airport}", callback_data="sched_keep")],
                [InlineKeyboardButton("Skip ⏭ (all airports)", callback_data="sched_skip_airport")],
            ])
        await query.message.reply_text(
            "Step 6/13: (Optional) Enter a specific <b>destination airport</b> IATA "
            "(e.g. <code>RMI</code>) or skip for all airports in selected countries:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return SCHED_AIRPORT
    else:
        cc = query.data.replace("dest_", "")
        selected.discard(cc) if cc in selected else selected.add(cc)
        await query.edit_message_reply_markup(reply_markup=dest_keyboard(selected))
        return SCHED_DEST


# ── Step 6: Airport (optional) ────────────────────────────────────────────────

async def skip_airport(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    _draft(ctx)["dest_airport"] = None
    return await _ask_date_from(update.callback_query.message, ctx)


async def keep_airport(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _ask_date_from(update.callback_query.message, ctx)


async def received_airport(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    if len(code) != 3 or not code.isalpha():
        await update.message.reply_text(
            "❌ Enter a valid 3-letter IATA (e.g. <code>RMI</code>) or skip:",
            parse_mode="HTML",
            reply_markup=skip_keyboard("sched_skip_airport"),
        )
        return SCHED_AIRPORT
    _draft(ctx)["dest_airport"] = code
    return await _ask_date_from(update.message, ctx)


async def _ask_date_from(msg, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if _editing(ctx):
        cur = _draft(ctx).get("date_from", "")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Keep: {cur}", callback_data="sched_keep")
        ]]) if cur else None
        await msg.reply_text(
            "Step 7/13: Enter <b>search start date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        await msg.reply_text(
            "Step 7/13: Enter <b>search start date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
        )
    return SCHED_DATE_FROM


# ── Step 7: Date from ─────────────────────────────────────────────────────────

async def received_date_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        text = update.message.text.strip()
        try:
            date.fromisoformat(text)
            _draft(ctx)["date_from"] = text
        except ValueError:
            await update.message.reply_text("❌ Use YYYY-MM-DD format (e.g. 2026-05-01):")
            return SCHED_DATE_FROM
        msg = update.message

    if _editing(ctx):
        cur = _draft(ctx).get("date_to", "")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Keep: {cur}", callback_data="sched_keep")
        ]]) if cur else None
        await msg.reply_text(
            "Step 8/13: Enter <b>search end date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        await msg.reply_text(
            "Step 8/13: Enter <b>search end date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
        )
    return SCHED_DATE_TO


# ── Step 8: Date to ───────────────────────────────────────────────────────────

async def received_date_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        text = update.message.text.strip()
        try:
            dt = date.fromisoformat(text)
            df_str = _draft(ctx).get("date_from", "")
            if df_str and dt <= date.fromisoformat(df_str):
                await update.message.reply_text("❌ End date must be after start date:")
                return SCHED_DATE_TO
            _draft(ctx)["date_to"] = text
        except ValueError:
            await update.message.reply_text("❌ Use YYYY-MM-DD format (e.g. 2026-08-31):")
            return SCHED_DATE_TO
        msg = update.message

    kb = nights_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, f"{_draft(ctx).get('min_nights', 1)} nights")
    await msg.reply_text(
        "Step 9/13: Select <b>minimum nights</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_MIN_NIGHTS


# ── Step 9: Min nights ────────────────────────────────────────────────────────

async def received_min_nights_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "nights_skip":
        _draft(ctx)["min_nights"] = 1
    elif query.data != "sched_keep":
        _draft(ctx)["min_nights"] = int(query.data.replace("nights_", ""))
    return await _ask_max_nights(query.message, ctx)


async def received_min_nights_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = int(update.message.text.strip())
        if not (1 <= val <= 30):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter 1–30:", reply_markup=nights_keyboard())
        return SCHED_MIN_NIGHTS
    _draft(ctx)["min_nights"] = val
    return await _ask_max_nights(update.message, ctx)


async def _ask_max_nights(msg, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    min_n = _draft(ctx).get("min_nights", 1)
    kb = nights_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, f"{_draft(ctx).get('max_nights', 14)} nights")
    await msg.reply_text(
        f"Step 10/13: Select <b>maximum nights</b> (≥ {min_n}):",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_MAX_NIGHTS


# ── Step 10: Max nights ───────────────────────────────────────────────────────

async def received_max_nights_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    min_n = _draft(ctx).get("min_nights", 1)
    if query.data == "nights_skip":
        _draft(ctx)["max_nights"] = 14
    elif query.data != "sched_keep":
        val = int(query.data.replace("nights_", ""))
        if val < min_n:
            await query.answer(f"Max must be ≥ {min_n}", show_alert=True)
            return SCHED_MAX_NIGHTS
        _draft(ctx)["max_nights"] = val
    return await _ask_depart_after(query.message, ctx)


async def received_max_nights_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    min_n = _draft(ctx).get("min_nights", 1)
    try:
        val = int(update.message.text.strip())
        if val < min_n:
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"❌ Enter ≥ {min_n}:", reply_markup=nights_keyboard())
        return SCHED_MAX_NIGHTS
    _draft(ctx)["max_nights"] = val
    return await _ask_depart_after(update.message, ctx)


async def _ask_depart_after(msg, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    kb = time_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, _draft(ctx).get("depart_after", "09:30"))
    await msg.reply_text(
        "Step 11/13: Select <b>earliest departure time</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_DEPART_AFTER


# ── Step 11: Depart after ─────────────────────────────────────────────────────

async def received_depart_after(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data != "sched_keep":
        _draft(ctx)["depart_after"] = query.data.replace("time_", "")

    kb = time_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, _draft(ctx).get("depart_before", "17:30"))
    await query.message.reply_text(
        "Step 12/13: Select <b>latest departure time</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_DEPART_BEFORE


# ── Step 12: Depart before ────────────────────────────────────────────────────

async def received_depart_before(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data != "sched_keep":
        _draft(ctx)["depart_before"] = query.data.replace("time_", "")

    if _editing(ctx):
        cur = _draft(ctx).get("max_price")
        cur_label = f"{cur:.0f} EUR" if cur else "no limit"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Keep: {cur_label}", callback_data="sched_keep")],
            [InlineKeyboardButton("Skip ⏭ (no limit)", callback_data="sched_skip_price")],
        ])
    else:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Skip ⏭ (no limit)", callback_data="sched_skip_price")
        ]])
    await query.message.reply_text(
        "Step 13/13: Enter <b>max price</b> in EUR, or skip:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return SCHED_MAX_PRICE


# ── Step 13: Max price ────────────────────────────────────────────────────────

async def received_max_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        val = float(update.message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Enter a positive number or skip:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Skip ⏭ (no limit)", callback_data="sched_skip_price")
            ]]),
        )
        return SCHED_MAX_PRICE
    _draft(ctx)["max_price"] = val
    return await _save_and_show(update, ctx)


async def skip_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    _draft(ctx)["max_price"] = None
    return await _save_and_show(update, ctx)


async def keep_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _save_and_show(update, ctx)


# ── Save ──────────────────────────────────────────────────────────────────────

async def _save_and_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d = _draft(ctx)
    bot = ctx.bot
    editing_id = ctx.user_data.get("sched_editing_id")

    d.setdefault("origin", "VIE")
    d.setdefault("country_codes", [])
    d.setdefault("dest_airport", None)
    d.setdefault("date_from", date.today().isoformat())
    d.setdefault("date_to", (date.today() + timedelta(days=90)).isoformat())
    d.setdefault("min_nights", 1)
    d.setdefault("max_nights", 14)
    d.setdefault("depart_after", "09:30")
    d.setdefault("depart_before", "17:30")
    d.setdefault("max_price", None)
    d.setdefault("days", "daily")
    d.setdefault("hour", 8)
    d.setdefault("minute", 0)

    if editing_id:
        update_schedule(editing_id, d, _schedules_file)
        saved = get_schedule(editing_id, _schedules_file)
        _add_job(saved, bot)
        action = "updated"
    else:
        saved = add_schedule(d, _schedules_file)
        _add_job(saved, bot)
        action = "created"

    _clear_draft(ctx)

    time_label = f"{d['hour']:02d}:{d['minute']:02d}"
    days_label = DAYS_LABELS.get(d["days"], d["days"])
    dest = d.get("dest_airport") or ", ".join(d.get("country_codes") or ["?"])
    await update.effective_message.reply_text(
        f"✅ Schedule <b>{d.get('name', 'Unnamed')}</b> {action}!\n"
        f"Runs: {days_label} at {time_label}  ·  {d['origin']} → {dest}\n"
        f"Window: {d['date_from']} – {d['date_to']}",
        parse_mode="HTML",
    )
    return await _show_menu(update, ctx, new_msg=True)


# ── Cancel / Timeout ──────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    await update.message.reply_text("Schedule wizard cancelled. Nothing was saved. /schedules to return.")
    return ConversationHandler.END


async def _on_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    try:
        msg = update.effective_message
        if msg:
            await msg.reply_text("⏱ Wizard timed out. Nothing was saved. /schedules to start again.")
    except Exception:
        pass
    return ConversationHandler.END


# ── APScheduler ───────────────────────────────────────────────────────────────

def _days_to_cron(days: str) -> str | None:
    return {"daily": None, "weekdays": "mon-fri", "weekends": "sat,sun"}.get(days, days)


def _add_job(schedule: dict, bot: Bot) -> None:
    day_of_week = _days_to_cron(schedule.get("days", "daily"))
    trigger_kw: dict = {"hour": schedule["hour"], "minute": schedule["minute"]}
    if day_of_week:
        trigger_kw["day_of_week"] = day_of_week
    scheduler.add_job(
        _run_search_job,
        trigger=CronTrigger(**trigger_kw),
        id=schedule["id"],
        args=[schedule, bot],
        replace_existing=True,
        misfire_grace_time=3600,
    )


def _remove_job(schedule_id: str) -> None:
    try:
        scheduler.remove_job(schedule_id)
    except Exception:
        pass


async def _run_search_job(schedule: dict, bot: Bot) -> None:
    from ..bot_history import load_history as load_bot_history, save_results as save_bot_results

    chat_id = schedule["chat_id"]
    origin = schedule.get("origin", "VIE")
    country_codes = schedule.get("country_codes") or []
    dest_airport = schedule.get("dest_airport")
    min_nights = schedule.get("min_nights", 1)
    max_nights = schedule.get("max_nights", 14)
    depart_after = schedule.get("depart_after", "09:30")
    depart_before = schedule.get("depart_before", "17:30")
    max_price = schedule.get("max_price")
    dest_label = dest_airport or ", ".join(country_codes)

    date_from = date.fromisoformat(schedule["date_from"])
    date_to = date.fromisoformat(schedule["date_to"])
    time_from = datetime.strptime(depart_after, "%H:%M").time()
    time_to = datetime.strptime(depart_before, "%H:%M").time()

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏰ <b>{schedule.get('name', 'Scheduled search')}</b>\n"
                f"Searching {origin} → {dest_label}  ({date_from} – {date_to})…"
            ),
            parse_mode="HTML",
        )
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
        text = f"❌ Scheduled search failed: {e}"

    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


def start_scheduler(bot: Bot, schedules_file: Path) -> None:
    global _schedules_file
    _schedules_file = schedules_file
    from ..schedules import load_schedules
    scheduler.start()
    for s in load_schedules(schedules_file):
        try:
            _add_job(s, bot)
        except Exception as e:
            print(f"Warning: could not load schedule {s.get('id')}: {e}")
    print(f"Scheduler started — {len(scheduler.get_jobs())} job(s) loaded.")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)


# ── Build handler ─────────────────────────────────────────────────────────────

def build_scheduler_handler() -> ConversationHandler:
    _timeout_handlers = [
        MessageHandler(filters.ALL, _on_timeout),
        CallbackQueryHandler(_on_timeout),
    ]
    return ConversationHandler(
        entry_points=[CommandHandler("schedules", show_schedules)],
        states={
            SCHED_MENU: [
                CallbackQueryHandler(handle_add, pattern="^sched_add$"),
                CallbackQueryHandler(handle_edit_select, pattern="^sched_edit_"),
                CallbackQueryHandler(handle_delete_select, pattern="^sched_delete_"),
                CallbackQueryHandler(handle_noop, pattern="^sched_noop$"),
            ],
            SCHED_NAME: [
                CallbackQueryHandler(received_name, pattern="^sched_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_name),
            ],
            SCHED_RUN_TIME: [
                CallbackQueryHandler(received_run_time, pattern="^(time_|sched_keep)"),
            ],
            SCHED_DAYS: [
                CallbackQueryHandler(received_days, pattern="^(days_|sched_keep)"),
            ],
            SCHED_ORIGIN: [
                CallbackQueryHandler(received_origin, pattern="^sched_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_origin),
            ],
            SCHED_DEST: [
                CallbackQueryHandler(toggle_dest, pattern="^dest_"),
            ],
            SCHED_AIRPORT: [
                CallbackQueryHandler(skip_airport, pattern="^sched_skip_airport$"),
                CallbackQueryHandler(keep_airport, pattern="^sched_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_airport),
            ],
            SCHED_DATE_FROM: [
                CallbackQueryHandler(received_date_from, pattern="^sched_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date_from),
            ],
            SCHED_DATE_TO: [
                CallbackQueryHandler(received_date_to, pattern="^sched_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date_to),
            ],
            SCHED_MIN_NIGHTS: [
                CallbackQueryHandler(received_min_nights_cb, pattern="^(nights_|sched_keep)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_min_nights_text),
            ],
            SCHED_MAX_NIGHTS: [
                CallbackQueryHandler(received_max_nights_cb, pattern="^(nights_|sched_keep)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_max_nights_text),
            ],
            SCHED_DEPART_AFTER: [
                CallbackQueryHandler(received_depart_after, pattern="^(time_|sched_keep)"),
            ],
            SCHED_DEPART_BEFORE: [
                CallbackQueryHandler(received_depart_before, pattern="^(time_|sched_keep)"),
            ],
            SCHED_MAX_PRICE: [
                CallbackQueryHandler(skip_price, pattern="^sched_skip_price$"),
                CallbackQueryHandler(keep_price, pattern="^sched_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_max_price),
            ],
            SCHED_DELETE_CONFIRM: [
                CallbackQueryHandler(delete_yes, pattern="^sched_del_yes$"),
                CallbackQueryHandler(delete_no, pattern="^sched_del_no$"),
            ],
            ConversationHandler.TIMEOUT: _timeout_handlers,
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", cancel),
            CommandHandler("help", cancel),
            CommandHandler("search", cancel),
            CommandHandler("find", cancel),
            CommandHandler("schedules", cancel),
        ],
        conversation_timeout=600,
        per_chat=True,
    )
