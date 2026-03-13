"""
/buchbinder — track Buchbinder car rental prices on exact dates.

7-step wizard:
  name → run-time → pickup station → return station
       → rental days → date from → date to
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

from ..buchbinder import fetch_prices
from ..buchbinder_trackers import (
    add_buchbinder_tracker,
    append_buchbinder_price,
    delete_buchbinder_tracker,
    get_buchbinder_tracker,
    get_user_buchbinder_trackers,
    load_buchbinder_trackers,
    update_buchbinder_tracker,
)

# ── States ────────────────────────────────────────────────────────────────────
(
    BUCH_MENU,
    BUCH_NAME,
    BUCH_RUN_TIME,
    BUCH_PICKUP,
    BUCH_DROPOFF,
    BUCH_DAYS,
    BUCH_DATE_FROM,
    BUCH_DATE_TO,
    BUCH_DELETE_CONFIRM,
) = range(9)

_buchbinder_file: Path = Path("./data/buchbinder_trackers.json")
buchbinder_scheduler = AsyncIOScheduler()

_AT_STATIONS = ["VIE", "VIW", "GRZ", "SZG", "INN", "KLU", "LNZ"]
_DAYS_PRESETS = [1, 2, 3, 5, 7, 10, 14]


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _time_keyboard() -> InlineKeyboardMarkup:
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
        row.append(InlineKeyboardButton(t, callback_data=f"buch_time_{t}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _station_keyboard(include_same: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for st in _AT_STATIONS:
        row.append(InlineKeyboardButton(st, callback_data=f"buch_st_{st}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if include_same:
        rows.append([InlineKeyboardButton("Same as pickup ↩", callback_data="buch_same_station")])
    return InlineKeyboardMarkup(rows)


def _days_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for d in _DAYS_PRESETS:
        row.append(InlineKeyboardButton(str(d), callback_data=f"buch_days_{d}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _keep_only(label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Keep: {label}", callback_data="buch_keep")]])


def _with_keep(kb: InlineKeyboardMarkup, label: str) -> InlineKeyboardMarkup:
    rows = list(kb.inline_keyboard) + [
        [InlineKeyboardButton(f"Keep: {label}", callback_data="buch_keep")]
    ]
    return InlineKeyboardMarkup(rows)


def _menu_keyboard(trackers: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in trackers:
        time_label = f"{t['hour']:02d}:{t['minute']:02d}"
        history = t.get("price_history", [])
        price_label = f"  {history[-1]['min_price']:.0f} EUR" if history else ""
        rows.append([InlineKeyboardButton(
            f"🚗 {t['name']}  {t['pickup']}→{t['dropoff']}  {t['rental_days']}d  "
            f"{t['date_from']}–{t['date_to']}{price_label}  ⏰{time_label}",
            callback_data="buch_noop",
        )])
        rows.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"buch_edit_{t['id']}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"buch_delete_{t['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Add new tracker", callback_data="buch_add")])
    return InlineKeyboardMarkup(rows)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _editing(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(ctx.user_data.get("buch_editing_id"))


def _draft(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    return ctx.user_data.setdefault("buch_draft", {})


def _clear_draft(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.user_data.pop("buch_draft", None)
    ctx.user_data.pop("buch_editing_id", None)


async def _show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, new_msg: bool = False) -> int:
    chat_id = update.effective_chat.id
    trackers = get_user_buchbinder_trackers(chat_id, _buchbinder_file)
    text = (
        f"🚗 <b>Your Buchbinder Trackers</b> ({len(trackers)})\n\nTap Edit or Delete on any entry:"
        if trackers else
        "🚗 <b>No Buchbinder trackers yet.</b>\nAdd one to get daily car rental price alerts!"
    )
    kb = _menu_keyboard(trackers)
    if update.callback_query and not new_msg:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            return BUCH_MENU
        except Exception:
            pass
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    return BUCH_MENU


# ── Result formatter ──────────────────────────────────────────────────────────

def _pct_tag(current: float, prev: float | None) -> str:
    if not prev or prev == 0:
        return ""
    pct = (current - prev) / prev * 100
    if abs(pct) < 0.5:
        return ""
    return f" {'↑' if pct > 0 else '↓'}{abs(pct):.0f}%"


def _short_date(d: date) -> str:
    return d.strftime("%b-%d")


def _format_result(tracker: dict, entry: dict) -> str:
    name = tracker["name"]
    pickup = tracker["pickup"]
    dropoff = tracker["dropoff"]
    rental_days = tracker["rental_days"]
    date_from = tracker["date_from"]
    date_to = tracker["date_to"]
    history = tracker.get("price_history", [])
    prev = history[-1] if history else None

    min_price = entry.get("min_price")
    per_day = entry.get("per_day", 0.0)
    best_pickup = entry.get("best_pickup", "")
    results = entry.get("results", [])

    if min_price is None:
        return (
            f"🚗 <b>{name}</b>  {rental_days} days\n"
            f"{pickup} → {dropoff}  ·  {date_from}–{date_to}\n\n"
            "<i>No available cars found for this period.</i>"
        )

    trend = _pct_tag(min_price, prev.get("min_price") if prev else None)

    lines = [
        f"🚗 <b>{name}</b>  {rental_days} days",
        f"{pickup} → {dropoff}  ·  {date_from}–{date_to}",
        "",
        f"Best this run: <b>{min_price:.0f} EUR</b> ({per_day:.0f}/day)  {trend}".rstrip(),
        "",
        "📅 Top dates:",
    ]

    for r in results[:5]:
        try:
            p_date = date.fromisoformat(r["pickup"])
            d_date = date.fromisoformat(r["dropoff"])
            p_short = _short_date(p_date)
            d_short = _short_date(d_date)
        except Exception:
            p_short = r.get("pickup", "")
            d_short = r.get("dropoff", "")

        car = r.get("car", "")
        price = r.get("price", 0.0)
        r_per_day = r.get("per_day", 0.0)
        gear = r.get("gear", "")
        unlimited = r.get("unlimited", False)

        gear_str = f"  {gear}" if gear in ("Auto", "Manual") else ""
        km_str = "  ∞" if unlimited else ""

        lines.append(
            f"{p_short}→{d_short}  {car}  <b>{price:.0f}€</b>  {r_per_day:.0f}/day{gear_str}{km_str}"
        )

    return "\n".join(lines)


# ── Entry ─────────────────────────────────────────────────────────────────────

async def show_buchbinder(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    ctx.user_data.pop("buch_delete_id", None)
    return await _show_menu(update, ctx)


# ── Menu callbacks ─────────────────────────────────────────────────────────────

async def handle_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return BUCH_MENU


async def handle_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    ctx.user_data["buch_draft"] = {"chat_id": update.effective_chat.id}
    ctx.user_data.pop("buch_editing_id", None)
    await update.callback_query.message.reply_text(
        "➕ <b>New Buchbinder Tracker</b>\n\nStep 1/7: Enter a <b>name</b> for this tracker:",
        parse_mode="HTML",
    )
    return BUCH_NAME


async def handle_edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    tracker_id = update.callback_query.data.replace("buch_edit_", "")
    t = get_buchbinder_tracker(tracker_id, _buchbinder_file)
    if not t:
        await update.callback_query.answer("Tracker not found.", show_alert=True)
        return await _show_menu(update, ctx)
    ctx.user_data["buch_editing_id"] = tracker_id
    ctx.user_data["buch_draft"] = dict(t)
    await update.callback_query.message.reply_text(
        f"✏️ <b>Editing: {t['name']}</b>\n\nStep 1/7: New <b>name</b> or keep:",
        parse_mode="HTML",
        reply_markup=_keep_only(t["name"]),
    )
    return BUCH_NAME


async def handle_delete_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    tracker_id = update.callback_query.data.replace("buch_delete_", "")
    t = get_buchbinder_tracker(tracker_id, _buchbinder_file)
    if not t:
        return await _show_menu(update, ctx)
    ctx.user_data["buch_delete_id"] = tracker_id
    await update.callback_query.edit_message_text(
        f"🗑️ Delete tracker <b>{t['name']}</b>?\nThis cannot be undone.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, delete", callback_data="buch_del_yes"),
            InlineKeyboardButton("❌ No, keep", callback_data="buch_del_no"),
        ]]),
    )
    return BUCH_DELETE_CONFIRM


# ── Delete confirm ─────────────────────────────────────────────────────────────

async def delete_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    tracker_id = ctx.user_data.pop("buch_delete_id", None)
    if tracker_id:
        delete_buchbinder_tracker(tracker_id, _buchbinder_file)
        _remove_job(tracker_id)
    await update.callback_query.message.reply_text(
        "🗑️ Tracker deleted. Use /buchbinder to manage your trackers."
    )
    return ConversationHandler.END


async def delete_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Deletion cancelled. Use /buchbinder to manage your trackers."
    )
    return ConversationHandler.END


# ── Step 1: Name ──────────────────────────────────────────────────────────────

async def received_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    else:
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("Please enter a name:")
            return BUCH_NAME
        _draft(ctx)["name"] = name

    kb = _time_keyboard()
    if _editing(ctx):
        d = _draft(ctx)
        kb = _with_keep(kb, f"{d.get('hour', 8):02d}:{d.get('minute', 0):02d}")
    await update.effective_message.reply_text(
        "Step 2/7: Select <b>daily check time</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return BUCH_RUN_TIME


# ── Step 2: Run time ──────────────────────────────────────────────────────────

async def received_run_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data != "buch_keep":
        h, m = map(int, query.data.replace("buch_time_", "").split(":"))
        _draft(ctx)["hour"] = h
        _draft(ctx)["minute"] = m

    kb = _station_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, _draft(ctx).get("pickup", "VIE"))
    await query.message.reply_text(
        "Step 3/7: Enter or select <b>pickup station</b> (IATA e.g. <code>VIE</code>):",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return BUCH_PICKUP


# ── Step 3: Pickup station ────────────────────────────────────────────────────

async def received_pickup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data != "buch_keep":
            _draft(ctx)["pickup"] = data.replace("buch_st_", "")
    else:
        code = update.message.text.strip().upper()
        if len(code) < 2 or len(code) > 5 or not code.isalpha():
            await update.message.reply_text(
                "❌ Enter a valid station code (e.g. <code>VIE</code>):",
                parse_mode="HTML",
            )
            return BUCH_PICKUP
        _draft(ctx)["pickup"] = code

    kb = _station_keyboard(include_same=True)
    if _editing(ctx):
        kb = _with_keep(kb, _draft(ctx).get("dropoff", "VIE"))
    await update.effective_message.reply_text(
        "Step 4/7: Enter or select <b>return station</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return BUCH_DROPOFF


# ── Step 4: Dropoff station ───────────────────────────────────────────────────

async def received_dropoff(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data == "buch_same_station":
            _draft(ctx)["dropoff"] = _draft(ctx).get("pickup", "VIE")
        elif data != "buch_keep":
            _draft(ctx)["dropoff"] = data.replace("buch_st_", "")
    else:
        code = update.message.text.strip().upper()
        if len(code) < 2 or len(code) > 5 or not code.isalpha():
            await update.message.reply_text(
                "❌ Enter a valid station code (e.g. <code>VIE</code>):",
                parse_mode="HTML",
            )
            return BUCH_DROPOFF
        _draft(ctx)["dropoff"] = code

    kb = _days_keyboard()
    if _editing(ctx):
        kb = _with_keep(kb, str(_draft(ctx).get("rental_days", 7)))
    await update.effective_message.reply_text(
        "Step 5/7: Enter or select <b>rental days</b> (1–30):",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return BUCH_DAYS


# ── Step 5: Rental days ───────────────────────────────────────────────────────

async def received_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data != "buch_keep":
            _draft(ctx)["rental_days"] = int(data.replace("buch_days_", ""))
    else:
        text = update.message.text.strip()
        try:
            days = int(text)
            if days < 1 or days > 30:
                raise ValueError
            _draft(ctx)["rental_days"] = days
        except ValueError:
            await update.message.reply_text("❌ Enter a number between 1 and 30:")
            return BUCH_DAYS

    if _editing(ctx):
        await update.effective_message.reply_text(
            "Step 6/7: Enter <b>search date from</b> (YYYY-MM-DD):",
            parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("date_from", "")),
        )
    else:
        await update.effective_message.reply_text(
            "Step 6/7: Enter <b>search date from</b> (YYYY-MM-DD):",
            parse_mode="HTML",
        )
    return BUCH_DATE_FROM


# ── Step 6: Date from ─────────────────────────────────────────────────────────

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
            await update.message.reply_text("❌ Use YYYY-MM-DD format (e.g. 2026-06-01):")
            return BUCH_DATE_FROM
        msg = update.message

    if _editing(ctx):
        await msg.reply_text(
            "Step 7/7: Enter <b>search date to</b> (YYYY-MM-DD):",
            parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("date_to", "")),
        )
    else:
        await msg.reply_text(
            "Step 7/7: Enter <b>search date to</b> (YYYY-MM-DD):",
            parse_mode="HTML",
        )
    return BUCH_DATE_TO


# ── Step 7: Date to ───────────────────────────────────────────────────────────

async def received_date_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        text = update.message.text.strip()
        try:
            dt = date.fromisoformat(text)
            from_str = _draft(ctx).get("date_from", "")
            if from_str and dt <= date.fromisoformat(from_str):
                await update.message.reply_text("❌ Date to must be after date from:")
                return BUCH_DATE_TO
            _draft(ctx)["date_to"] = text
        except ValueError:
            await update.message.reply_text("❌ Use YYYY-MM-DD format (e.g. 2026-06-30):")
            return BUCH_DATE_TO
        msg = update.message

    return await _save_and_end(msg, ctx)


# ── Save ──────────────────────────────────────────────────────────────────────

async def _save_and_end(msg, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d = _draft(ctx)
    bot = ctx.bot
    editing_id = ctx.user_data.get("buch_editing_id")

    d.setdefault("pickup", "VIE")
    d.setdefault("dropoff", "VIE")
    d.setdefault("rental_days", 7)
    d.setdefault("date_from", date.today().isoformat())
    d.setdefault("date_to", date.today().isoformat())
    d.setdefault("hour", 8)
    d.setdefault("minute", 0)

    if editing_id:
        update_buchbinder_tracker(editing_id, d, _buchbinder_file)
        saved = get_buchbinder_tracker(editing_id, _buchbinder_file)
        _add_job(saved, bot)
        action = "updated"
    else:
        saved = add_buchbinder_tracker(d, _buchbinder_file)
        _add_job(saved, bot)
        action = "created"

    _clear_draft(ctx)

    time_label = f"{d['hour']:02d}:{d['minute']:02d}"
    await msg.reply_text(
        f"✅ Tracker <b>{d.get('name', 'Unnamed')}</b> {action}!\n"
        f"Pickup: {d['pickup']} → Return: {d['dropoff']}\n"
        f"Rental: {d['rental_days']} days\n"
        f"Dates: {d['date_from']} – {d['date_to']}\n"
        f"Daily check at {time_label}\n\n"
        "Use /buchbinder to manage your trackers.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ── Cancel / Timeout ──────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    await update.message.reply_text(
        "Buchbinder wizard cancelled. Nothing was saved. /buchbinder to return."
    )
    return ConversationHandler.END


async def _on_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    has_draft = bool(ctx.user_data.get("buch_draft"))
    _clear_draft(ctx)
    try:
        msg = update.effective_message
        if msg:
            text = (
                "⏱ Wizard timed out. Nothing was saved. /buchbinder to start again."
                if has_draft else
                "⏱ Session expired. /buchbinder to open your trackers."
            )
            await msg.reply_text(text)
    except Exception:
        pass
    return ConversationHandler.END


# ── APScheduler ───────────────────────────────────────────────────────────────

def _add_job(tracker: dict, bot: Bot) -> None:
    buchbinder_scheduler.add_job(
        _run_buchbinder_job,
        trigger=CronTrigger(hour=tracker["hour"], minute=tracker["minute"]),
        id=tracker["id"],
        args=[tracker["id"], bot],
        replace_existing=True,
        misfire_grace_time=3600,
    )


def _remove_job(tracker_id: str) -> None:
    try:
        buchbinder_scheduler.remove_job(tracker_id)
    except Exception:
        pass


async def _run_buchbinder_job(tracker_id: str, bot: Bot) -> None:
    tracker = get_buchbinder_tracker(tracker_id, _buchbinder_file)
    if not tracker:
        return

    chat_id = tracker["chat_id"]
    pickup = tracker["pickup"]
    dropoff = tracker["dropoff"]
    rental_days = tracker["rental_days"]
    date_from = date.fromisoformat(tracker["date_from"])
    date_to = date.fromisoformat(tracker["date_to"])

    try:
        day_results: list[dict] = []
        current = date_from
        while current <= date_to:
            dropoff_date = current + timedelta(days=rental_days)
            # allow dropoff to extend beyond date_to
            if dropoff_date > date_to + timedelta(days=rental_days):
                current += timedelta(days=1)
                continue

            try:
                rates = await asyncio.to_thread(
                    fetch_prices,
                    pickup=pickup,
                    dropoff=dropoff,
                    pickup_date=current,
                    dropoff_date=dropoff_date,
                )
                if rates:
                    best = rates[0]
                    day_results.append({
                        "pickup": current.isoformat(),
                        "dropoff": dropoff_date.isoformat(),
                        "price": best["total_price"],
                        "per_day": best["per_day"],
                        "car": best["label"],
                        "gear": best["gear"],
                        "unlimited": best["unlimited_km"],
                    })
            except Exception:
                pass

            await asyncio.sleep(0.5)
            current += timedelta(days=1)

        # Reload tracker to get latest history before saving new entry
        tracker = get_buchbinder_tracker(tracker_id, _buchbinder_file)

        if day_results:
            cheapest = min(day_results, key=lambda r: r["price"])
            top10 = sorted(day_results, key=lambda r: r["price"])[:10]
            entry = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "min_price": cheapest["price"],
                "per_day": cheapest["per_day"],
                "best_pickup": cheapest["pickup"],
                "results": top10,
            }
        else:
            entry = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "min_price": None,
                "per_day": None,
                "best_pickup": None,
                "results": [],
            }

        append_buchbinder_price(tracker_id, entry, _buchbinder_file)
        text = _format_result(tracker, entry)
    except Exception as e:
        text = f"❌ Price check failed for <b>{tracker['name']}</b>: {e}"

    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


def start_buchbinder_scheduler(bot: Bot, file: Path) -> None:
    global _buchbinder_file
    _buchbinder_file = file
    buchbinder_scheduler.start()
    loaded = 0
    for t in load_buchbinder_trackers(file):
        try:
            _add_job(t, bot)
            loaded += 1
        except Exception as e:
            print(f"Warning: could not load buchbinder tracker {t.get('id')}: {e}")
    print(f"Buchbinder scheduler started — {loaded} job(s) loaded.")


def stop_buchbinder_scheduler() -> None:
    buchbinder_scheduler.shutdown(wait=False)


# ── Build handler ─────────────────────────────────────────────────────────────

def build_buchbinder_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("buchbinder", show_buchbinder)],
        states={
            BUCH_MENU: [
                CallbackQueryHandler(handle_add, pattern="^buch_add$"),
                CallbackQueryHandler(handle_edit_select, pattern="^buch_edit_"),
                CallbackQueryHandler(handle_delete_select, pattern="^buch_delete_"),
                CallbackQueryHandler(handle_noop, pattern="^buch_noop$"),
            ],
            BUCH_NAME: [
                CallbackQueryHandler(received_name, pattern="^buch_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_name),
            ],
            BUCH_RUN_TIME: [
                CallbackQueryHandler(received_run_time, pattern="^(buch_time_|buch_keep)"),
            ],
            BUCH_PICKUP: [
                CallbackQueryHandler(received_pickup, pattern="^(buch_st_|buch_keep)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_pickup),
            ],
            BUCH_DROPOFF: [
                CallbackQueryHandler(received_dropoff, pattern="^(buch_st_|buch_same_station|buch_keep)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_dropoff),
            ],
            BUCH_DAYS: [
                CallbackQueryHandler(received_days, pattern="^(buch_days_|buch_keep)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_days),
            ],
            BUCH_DATE_FROM: [
                CallbackQueryHandler(received_date_from, pattern="^buch_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date_from),
            ],
            BUCH_DATE_TO: [
                CallbackQueryHandler(received_date_to, pattern="^buch_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date_to),
            ],
            BUCH_DELETE_CONFIRM: [
                CallbackQueryHandler(delete_yes, pattern="^buch_del_yes$"),
                CallbackQueryHandler(delete_no, pattern="^buch_del_no$"),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, _on_timeout),
                CallbackQueryHandler(_on_timeout),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", cancel),
            CommandHandler("help", cancel),
            CommandHandler("search", cancel),
            CommandHandler("find", cancel),
            CommandHandler("schedules", cancel),
            CommandHandler("track", cancel),
            CommandHandler("buchbinder", cancel),
        ],
        conversation_timeout=600,
        per_chat=True,
    )
