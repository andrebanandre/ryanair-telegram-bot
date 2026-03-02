"""Telegram push notifications — send to all registered chats."""

from __future__ import annotations

import asyncio
from pathlib import Path


async def _send_all(token: str, text: str, chats_file: Path) -> None:
    from telegram import Bot
    from .chats import load_chats

    bot = Bot(token=token)
    for c in load_chats(chats_file):
        try:
            await bot.send_message(chat_id=c["chat_id"], text=text, parse_mode="HTML")
        except Exception:
            pass  # skip unreachable/blocked chats


def notify(token: str, text: str, chats_file: Path) -> None:
    """Synchronously send a Telegram message to all registered chats."""
    asyncio.run(_send_all(token, text, chats_file))
