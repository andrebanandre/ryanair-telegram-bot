"""
/track — track cheapest price for a specific route on exact dates.

6-step wizard:
  name → run-time → origin airport → departure date
       → destination airport → return date
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
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

from ..flights import fetch_round_trips
from ..deals import evaluate_deal
from ..trackers import (
    add_tracker, delete_tracker, get_tracker, get_user_trackers, update_tracker, append_price,
)

# ── States ────────────────────────────────────────────────────────────────────
(
    TRACK_MENU,
    TRACK_NAME,
    TRACK_RUN_TIME,
    TRACK_ORIGIN,
    TRACK_DEPART_DATE,
    TRACK_DEST,
    TRACK_RETURN_DATE,
    TRACK_DELETE_CONFIRM,
) = range(8)

_trackers_file: Path = Path("./data/trackers.json")
tracker_scheduler = AsyncIOScheduler()


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
        row.append(InlineKeyboardButton(t, callback_data=f"trk_time_{t}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _keep_only(label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Keep: {label}", callback_data="trk_keep")]])


def _with_keep(kb: InlineKeyboardMarkup, label: str) -> InlineKeyboardMarkup:
    rows = list(kb.inline_keyboard) + [
        [InlineKeyboardButton(f"Keep: {label}", callback_data="trk_keep")]
    ]
    return InlineKeyboardMarkup(rows)


def _menu_keyboard(trackers: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in trackers:
        time_label = f"{t['hour']:02d}:{t['minute']:02d}"
        history = t.get("price_history", [])
        price_label = f"  {history[-1]['total_price']:.0f} EUR" if history else ""
        rows.append([InlineKeyboardButton(
            f"📍 {t['name']}  {t['origin']}→{t['dest']}  {t['date_from']}→{t['date_to']}{price_label}  ⏰{time_label}",
            callback_data="trk_noop",
        )])
        rows.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"trk_edit_{t['id']}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"trk_delete_{t['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Add new tracker", callback_data="trk_add")])
    return InlineKeyboardMarkup(rows)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _editing(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(ctx.user_data.get("trk_editing_id"))


def _draft(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    return ctx.user_data.setdefault("trk_draft", {})


def _clear_draft(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.user_data.pop("trk_draft", None)
    ctx.user_data.pop("trk_editing_id", None)


async def _show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, new_msg: bool = False) -> int:
    chat_id = update.effective_chat.id
    trackers = get_user_trackers(chat_id, _trackers_file)
    text = (
        f"📍 <b>Your Price Trackers</b> ({len(trackers)})\n\nTap Edit or Delete on any entry:"
        if trackers else
        "📍 <b>No trackers yet.</b>\nAdd one to get daily price alerts for specific flights!"
    )
    kb = _menu_keyboard(trackers)
    if update.callback_query and not new_msg:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            return TRACK_MENU
        except Exception:
            pass
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    return TRACK_MENU


# ── Result formatter ──────────────────────────────────────────────────────────

def _pct_tag(current: float, prev: float | None) -> str:
    if not prev or prev == 0:
        return ""
    pct = (current - prev) / prev * 100
    if abs(pct) < 0.5:
        return ""
    return f" {'↑' if pct > 0 else '↓'}{abs(pct):.0f}%"


def format_track_result(tracker: dict, results: list[dict]) -> str:
    name = tracker["name"]
    origin = tracker["origin"]
    dest = tracker["dest"]
    history = tracker.get("price_history", [])
    prev = history[-1] if history else None  # entry saved BEFORE this run

    header = (
        f"📍 <b>{name}</b>\n"
        f"{origin} → {dest}  {tracker['date_from']} → {tracker['date_to']}\n"
    )

    if not results:
        return header + "\n<i>No flights found for these dates.</i>"

    shown = sorted(results, key=lambda r: r["total_price"])
    best = shown[0]
    currency = best["currency"]
    out_p = best.get("outbound_price", 0.0)
    ret_p = best.get("return_price", 0.0)
    total = best["total_price"]
    out_dt = best["outbound_depart"][5:]   # MM-DD HH:MM
    ret_dt = best["return_depart"][5:]
    deal = " 🔥" if best.get("is_deal") else ""

    out_trend = _pct_tag(out_p, prev.get("outbound_price") if prev else None)
    ret_trend = _pct_tag(ret_p, prev.get("return_price") if prev else None)
    total_trend = _pct_tag(total, prev.get("total_price") if prev else None)

    lines = [
        header,
        f"<b>FROM</b>: {best['outbound_flight']}  {out_dt}  {origin}→{dest}  "
        f"<b>{out_p:.0f} {currency}</b>{out_trend}",
        f"<b>BACK</b>: {best['return_flight']}  {ret_dt}  {dest}→{origin}  "
        f"<b>{ret_p:.0f} {currency}</b>{ret_trend}",
        f"{best['nights']}n · <b>{total:.0f} {currency}</b>{total_trend}{deal}",
    ]

    # Show up to 3 alternative options
    if len(shown) > 1:
        alts = [
            f"{r['outbound_flight']} {r['outbound_depart'][8:13]} {r['total_price']:.0f}"
            for r in shown[1:4]
        ]
        lines.append(f"\n<i>Also: {', '.join(alts)} {currency}</i>")

    return "\n".join(lines)


# ── Entry ─────────────────────────────────────────────────────────────────────

async def show_trackers(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    ctx.user_data.pop("trk_delete_id", None)
    return await _show_menu(update, ctx)


# ── Menu callbacks ─────────────────────────────────────────────────────────────

async def handle_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return TRACK_MENU


async def handle_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    ctx.user_data["trk_draft"] = {"chat_id": update.effective_chat.id}
    ctx.user_data.pop("trk_editing_id", None)
    await update.callback_query.message.reply_text(
        "➕ <b>New Price Tracker</b>\n\nStep 1/6: Enter a <b>name</b> for this tracker:",
        parse_mode="HTML",
    )
    return TRACK_NAME


async def handle_edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    tracker_id = update.callback_query.data.replace("trk_edit_", "")
    t = get_tracker(tracker_id, _trackers_file)
    if not t:
        await update.callback_query.answer("Tracker not found.", show_alert=True)
        return await _show_menu(update, ctx)
    ctx.user_data["trk_editing_id"] = tracker_id
    ctx.user_data["trk_draft"] = dict(t)
    await update.callback_query.message.reply_text(
        f"✏️ <b>Editing: {t['name']}</b>\n\nStep 1/6: New <b>name</b> or keep:",
        parse_mode="HTML",
        reply_markup=_keep_only(t["name"]),
    )
    return TRACK_NAME


async def handle_delete_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    tracker_id = update.callback_query.data.replace("trk_delete_", "")
    t = get_tracker(tracker_id, _trackers_file)
    if not t:
        return await _show_menu(update, ctx)
    ctx.user_data["trk_delete_id"] = tracker_id
    await update.callback_query.edit_message_text(
        f"🗑️ Delete tracker <b>{t['name']}</b>?\nThis cannot be undone.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, delete", callback_data="trk_del_yes"),
            InlineKeyboardButton("❌ No, keep", callback_data="trk_del_no"),
        ]]),
    )
    return TRACK_DELETE_CONFIRM


# ── Delete confirm ─────────────────────────────────────────────────────────────

async def delete_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    tracker_id = ctx.user_data.pop("trk_delete_id", None)
    if tracker_id:
        delete_tracker(tracker_id, _trackers_file)
        _remove_job(tracker_id)
    await update.callback_query.message.reply_text(
        "🗑️ Tracker deleted. Use /track to manage your trackers."
    )
    return ConversationHandler.END


async def delete_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Deletion cancelled. Use /track to manage your trackers."
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
            return TRACK_NAME
        _draft(ctx)["name"] = name

    kb = _time_keyboard()
    if _editing(ctx):
        d = _draft(ctx)
        kb = _with_keep(kb, f"{d.get('hour', 8):02d}:{d.get('minute', 0):02d}")
    await update.effective_message.reply_text(
        "Step 2/6: Select <b>daily check time</b>:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return TRACK_RUN_TIME


# ── Step 2: Run time ──────────────────────────────────────────────────────────

async def received_run_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data != "trk_keep":
        h, m = map(int, query.data.replace("trk_time_", "").split(":"))
        _draft(ctx)["hour"] = h
        _draft(ctx)["minute"] = m

    if _editing(ctx):
        await query.message.reply_text(
            "Step 3/6: Enter <b>origin airport</b> IATA (e.g. <code>VIE</code>):",
            parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("origin", "VIE")),
        )
    else:
        await query.message.reply_text(
            "Step 3/6: Enter <b>origin airport</b> IATA (e.g. <code>VIE</code>):",
            parse_mode="HTML",
        )
    return TRACK_ORIGIN


# ── Step 3: Origin ────────────────────────────────────────────────────────────

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
            return TRACK_ORIGIN
        _draft(ctx)["origin"] = code

    if _editing(ctx):
        await update.effective_message.reply_text(
            "Step 4/6: Enter <b>departure date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("date_from", "")),
        )
    else:
        await update.effective_message.reply_text(
            "Step 4/6: Enter <b>departure date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
        )
    return TRACK_DEPART_DATE


# ── Step 4: Departure date ────────────────────────────────────────────────────

async def received_depart_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
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
            return TRACK_DEPART_DATE
        msg = update.message

    if _editing(ctx):
        await msg.reply_text(
            "Step 5/6: Enter <b>destination airport</b> IATA (e.g. <code>ATH</code>):",
            parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("dest", "")),
        )
    else:
        await msg.reply_text(
            "Step 5/6: Enter <b>destination airport</b> IATA (e.g. <code>ATH</code>):",
            parse_mode="HTML",
        )
    return TRACK_DEST


# ── Step 5: Destination ───────────────────────────────────────────────────────

async def received_dest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    else:
        code = update.message.text.strip().upper()
        if len(code) != 3 or not code.isalpha():
            await update.message.reply_text(
                "❌ Enter a valid 3-letter IATA (e.g. <code>ATH</code>):",
                parse_mode="HTML",
            )
            return TRACK_DEST
        _draft(ctx)["dest"] = code

    if _editing(ctx):
        await update.effective_message.reply_text(
            "Step 6/6: Enter <b>return date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
            reply_markup=_keep_only(_draft(ctx).get("date_to", "")),
        )
    else:
        await update.effective_message.reply_text(
            "Step 6/6: Enter <b>return date</b> (YYYY-MM-DD):",
            parse_mode="HTML",
        )
    return TRACK_RETURN_DATE


# ── Step 6: Return date ───────────────────────────────────────────────────────

async def received_return_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        text = update.message.text.strip()
        try:
            ret = date.fromisoformat(text)
            dep_str = _draft(ctx).get("date_from", "")
            if dep_str and ret <= date.fromisoformat(dep_str):
                await update.message.reply_text("❌ Return date must be after departure date:")
                return TRACK_RETURN_DATE
            _draft(ctx)["date_to"] = text
        except ValueError:
            await update.message.reply_text("❌ Use YYYY-MM-DD format (e.g. 2026-06-08):")
            return TRACK_RETURN_DATE
        msg = update.message

    return await _save_and_end(msg, ctx)


# ── Save ──────────────────────────────────────────────────────────────────────

async def _save_and_end(msg, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d = _draft(ctx)
    bot = ctx.bot
    editing_id = ctx.user_data.get("trk_editing_id")

    d.setdefault("origin", "VIE")
    d.setdefault("dest", "ATH")
    d.setdefault("date_from", date.today().isoformat())
    d.setdefault("date_to", date.today().isoformat())
    d.setdefault("hour", 8)
    d.setdefault("minute", 0)

    if editing_id:
        update_tracker(editing_id, d, _trackers_file)
        saved = get_tracker(editing_id, _trackers_file)
        _add_job(saved, bot)
        action = "updated"
    else:
        saved = add_tracker(d, _trackers_file)
        _add_job(saved, bot)
        action = "created"

    _clear_draft(ctx)

    time_label = f"{d['hour']:02d}:{d['minute']:02d}"
    await msg.reply_text(
        f"✅ Tracker <b>{d.get('name', 'Unnamed')}</b> {action}!\n"
        f"Tracking: {d['origin']} → {d['dest']}\n"
        f"Dates: {d['date_from']} → {d['date_to']}\n"
        f"Daily check at {time_label}\n\n"
        "Use /track to manage your trackers.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ── Cancel / Timeout ──────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(ctx)
    await update.message.reply_text("Tracker wizard cancelled. Nothing was saved. /track to return.")
    return ConversationHandler.END


async def _on_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    has_draft = bool(ctx.user_data.get("trk_draft"))
    _clear_draft(ctx)
    try:
        msg = update.effective_message
        if msg:
            text = (
                "⏱ Wizard timed out. Nothing was saved. /track to start again."
                if has_draft else
                "⏱ Session expired. /track to open your trackers."
            )
            await msg.reply_text(text)
    except Exception:
        pass
    return ConversationHandler.END


# ── APScheduler ───────────────────────────────────────────────────────────────

def _add_job(tracker: dict, bot: Bot) -> None:
    tracker_scheduler.add_job(
        _run_track_job,
        trigger=CronTrigger(hour=tracker["hour"], minute=tracker["minute"]),
        id=tracker["id"],
        args=[tracker["id"], bot],
        replace_existing=True,
        misfire_grace_time=3600,
    )


def _remove_job(tracker_id: str) -> None:
    try:
        tracker_scheduler.remove_job(tracker_id)
    except Exception:
        pass


async def _run_track_job(tracker_id: str, bot: Bot) -> None:
    tracker = get_tracker(tracker_id, _trackers_file)
    if not tracker:
        return

    chat_id = tracker["chat_id"]
    origin = tracker["origin"]
    dest = tracker["dest"]
    dep = date.fromisoformat(tracker["date_from"])
    ret = date.fromisoformat(tracker["date_to"])
    nights = (ret - dep).days

    if nights <= 0:
        await bot.send_message(chat_id=chat_id,
                               text=f"⚠️ Tracker <b>{tracker['name']}</b>: return date must be after departure.",
                               parse_mode="HTML")
        return

    try:
        flights = await asyncio.to_thread(
            fetch_round_trips,
            origin=origin,
            country_codes=[],
            dest_airport=dest,
            date_from=dep,
            date_to=dep,          # exact departure date
            time_from=datetime.strptime("00:00", "%H:%M").time(),
            time_to=datetime.strptime("23:59", "%H:%M").time(),
            max_price=None,
            min_nights=nights,
            max_nights=nights,    # exact return date
        )
        results = [evaluate_deal(f, {}, 20.0) for f in flights]

        # Reload tracker to get latest history before saving new entry
        tracker = get_tracker(tracker_id, _trackers_file)
        text = format_track_result(tracker, results)

        if results:
            best = min(results, key=lambda r: r["total_price"])
            entry = {
                "outbound_price": best.get("outbound_price", 0.0),
                "return_price": best.get("return_price", 0.0),
                "total_price": best["total_price"],
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            append_price(tracker_id, entry, _trackers_file)
    except Exception as e:
        text = f"❌ Price check failed for <b>{tracker['name']}</b>: {e}"

    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


def start_tracker_scheduler(bot: Bot, trackers_file: Path) -> None:
    global _trackers_file
    _trackers_file = trackers_file
    from ..trackers import load_trackers
    tracker_scheduler.start()
    loaded = 0
    for t in load_trackers(trackers_file):
        try:
            _add_job(t, bot)
            loaded += 1
        except Exception as e:
            print(f"Warning: could not load tracker {t.get('id')}: {e}")
    print(f"Tracker scheduler started — {loaded} job(s) loaded.")


def stop_tracker_scheduler() -> None:
    tracker_scheduler.shutdown(wait=False)


# ── Build handler ─────────────────────────────────────────────────────────────

def build_tracker_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("track", show_trackers)],
        states={
            TRACK_MENU: [
                CallbackQueryHandler(handle_add, pattern="^trk_add$"),
                CallbackQueryHandler(handle_edit_select, pattern="^trk_edit_"),
                CallbackQueryHandler(handle_delete_select, pattern="^trk_delete_"),
                CallbackQueryHandler(handle_noop, pattern="^trk_noop$"),
            ],
            TRACK_NAME: [
                CallbackQueryHandler(received_name, pattern="^trk_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_name),
            ],
            TRACK_RUN_TIME: [
                CallbackQueryHandler(received_run_time, pattern="^(trk_time_|trk_keep)"),
            ],
            TRACK_ORIGIN: [
                CallbackQueryHandler(received_origin, pattern="^trk_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_origin),
            ],
            TRACK_DEPART_DATE: [
                CallbackQueryHandler(received_depart_date, pattern="^trk_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_depart_date),
            ],
            TRACK_DEST: [
                CallbackQueryHandler(received_dest, pattern="^trk_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_dest),
            ],
            TRACK_RETURN_DATE: [
                CallbackQueryHandler(received_return_date, pattern="^trk_keep$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_return_date),
            ],
            TRACK_DELETE_CONFIRM: [
                CallbackQueryHandler(delete_yes, pattern="^trk_del_yes$"),
                CallbackQueryHandler(delete_no, pattern="^trk_del_no$"),
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
        ],
        conversation_timeout=600,
        per_chat=True,
    )
