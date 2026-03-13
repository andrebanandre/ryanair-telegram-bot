"""Telegram bot entry point (polling mode)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .wizard import build_wizard_handler
from .query import find_command
from .scheduler_conv import build_scheduler_handler, start_scheduler, stop_scheduler
from .tracker_conv import build_tracker_handler, start_tracker_scheduler, stop_tracker_scheduler
from .buchbinder_conv import build_buchbinder_handler, start_buchbinder_scheduler, stop_buchbinder_scheduler

HELP_TEXT = """<b>Ryanair Deal Tracker Bot</b>

Commands:
/search — Interactive flight search wizard
/find ORIGIN DEST DATE_FROM DATE_TO [MIN_NIGHTS [MAX_NIGHTS [MAX_PRICE]]]
  — Quick one-liner search
/schedules — Manage scheduled automatic searches (date ranges)
/track — Track price for a specific route on exact dates
/buchbinder — Track Buchbinder car rental prices on exact dates

Examples:
<code>/find VIE GR 2026-05-01 2026-06-30 7 8</code>
<code>/find VIE GR,IT,ES 2026-05-01 2026-07-31 5 10 300</code>
"""


def _chats_file() -> Path:
    return Path(os.environ.get("CHATS_FILE", "./data/chats.json"))


def _schedules_file() -> Path:
    return Path(os.environ.get("SCHEDULES_FILE", "./schedules.json"))


def _trackers_file() -> Path:
    return Path(os.environ.get("TRACKERS_FILE", "./data/trackers.json"))


def _buchbinder_file() -> Path:
    return Path(os.environ.get("BUCHBINDER_FILE", "./data/buchbinder_trackers.json"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from ..chats import register_chat

    chat = update.effective_chat
    is_new = register_chat(
        chat_id=chat.id,
        first_name=chat.first_name or "",
        username=chat.username or "",
        path=_chats_file(),
    )
    if is_new:
        print(f"Registered new chat: {chat.id} ({chat.first_name or chat.username})")
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def _post_init(app: Application) -> None:
    start_scheduler(app.bot, _schedules_file())
    start_tracker_scheduler(app.bot, _trackers_file())
    start_buchbinder_scheduler(app.bot, _buchbinder_file())


async def _post_stop(app: Application) -> None:
    stop_scheduler()
    stop_tracker_scheduler()
    stop_buchbinder_scheduler()


def main() -> None:
    load_dotenv()
    token = os.environ.get("TG_TOKEN")
    if not token:
        raise RuntimeError(
            "TG_TOKEN not set. Create a .env file with TG_TOKEN=<your token>."
        )

    app = (
        Application.builder()
        .token(token)
        .post_init(_post_init)
        .post_stop(_post_stop)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(build_wizard_handler())
    app.add_handler(build_scheduler_handler())
    app.add_handler(build_tracker_handler())
    app.add_handler(build_buchbinder_handler())
    app.add_handler(CommandHandler("find", find_command))

    print("Bot running… Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
