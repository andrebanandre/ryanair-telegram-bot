"""FastAPI webhook server for the Telegram bot.

Run with:
    fastapi dev ryanair_tracker/bot/server.py
    # or
    uvicorn ryanair_tracker.bot.server:app --reload

Requires environment variables:
    TG_TOKEN    — Telegram bot token
    WEBHOOK_URL — Your public HTTPS URL (e.g. from ngrok: https://abc123.ngrok.io)
                  The bot will register /webhook as the Telegram webhook endpoint.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler

load_dotenv()

_tg_app: Application | None = None


def _build_tg_app(token: str) -> Application:
    from .wizard import build_wizard_handler
    from .query import find_command
    from .app import start, help_command

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(build_wizard_handler())
    app.add_handler(CommandHandler("find", find_command))
    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tg_app
    token = os.environ.get("TG_TOKEN")
    if not token:
        raise RuntimeError("TG_TOKEN not set")

    _tg_app = _build_tg_app(token)
    await _tg_app.initialize()
    await _tg_app.start()

    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        await _tg_app.bot.set_webhook(f"{webhook_url}/webhook")
        print(f"Webhook registered: {webhook_url}/webhook")
    else:
        print("WEBHOOK_URL not set — Telegram webhook not registered.")
        print("Set WEBHOOK_URL=https://<your-public-url> in .env to enable.")

    yield

    await _tg_app.stop()
    await _tg_app.shutdown()


app = FastAPI(title="Ryanair Tracker Bot", lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    data = await request.json()
    update = Update.de_json(data, _tg_app.bot)
    await _tg_app.process_update(update)
    return Response(status_code=200)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
