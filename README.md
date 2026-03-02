# ryanair-telegram-bot

A personal Telegram bot that searches Ryanair for cheap round-trip flights, tracks price history, and sends alerts when deals appear.

> **Disclaimer:** This is an independent personal project and is **not affiliated with, endorsed by, or connected to Ryanair DAC** in any way. Use at your own risk. The authors are not responsible for any inaccuracies in flight data, missed bookings, financial loss, or any other consequences arising from the use of this software. Always verify prices and availability directly on [ryanair.com](https://www.ryanair.com) before booking.

---

## Features

- `/search` — interactive 10-step wizard to search flights with full control over dates, nights, departure times, and destination
- `/schedules` — set up recurring searches (cron-based) that run automatically and push results to your Telegram
- `/find` — quick one-liner search command
- Price range tracking — shows min/max price per search and ↑/↓% trend vs previous run
- Deal detection — flags flights significantly below historical baseline

---

## Quick Start (Docker — recommended)

### 1. Get a bot token

Talk to [@BotFather](https://t.me/BotFather) on Telegram, create a bot, copy the token.

### 2. Clone and configure

```bash
git clone https://github.com/andrebanandre/ryanair-telegram-bot
cd ryanair-telegram-bot
cp .env.example .env
# Edit .env and set your TG_TOKEN
```

### 3. Run

```bash
mkdir -p data
docker compose up -d
docker compose logs -f   # verify it's running
```

Start a chat with your bot and send `/start`.

---

## Configuration

`.env` file (copy from `.env.example`):

```env
TG_TOKEN=your_bot_token_here

# Optional — override default paths
# CHATS_FILE=./data/chats.json
# SCHEDULES_FILE=./data/schedules.json
```

All persistent state is stored in `./data/` (mounted as a Docker volume):

| File                    | Contents                                    |
| ----------------------- | ------------------------------------------- |
| `data/chats.json`       | Registered chat IDs (populated on `/start`) |
| `data/schedules.json`   | Saved scheduler configs                     |
| `data/bot_history.json` | Price history per route for trend tracking  |

---

## Bot Commands

| Command                                                           | Description                                 |
| ----------------------------------------------------------------- | ------------------------------------------- |
| `/start`                                                          | Register your chat and show welcome message |
| `/help`                                                           | Show available commands                     |
| `/search`                                                         | Start interactive flight search wizard      |
| `/find ORIGIN DEST DATE_FROM DATE_TO [MIN_N [MAX_N [MAX_PRICE]]]` | Quick search                                |
| `/schedules`                                                      | Manage recurring scheduled searches         |
| `/cancel`                                                         | Cancel any in-progress wizard               |

### `/find` examples

```
/find VIE GR 2026-05-01 2026-07-31
/find VIE IT,ES 2026-06-01 2026-08-31 7 10 200
/find VIE RMI 2026-05-01 2026-06-30 7 8
```

`DEST` can be:

- A 2-letter country code: `GR`, `IT`, `ES`, `PT`, `HR`
- Multiple countries comma-separated: `GR,IT`
- A specific 3-letter airport IATA: `RMI`, `ATH`

---

## Local Development

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e .

cp .env.example .env   # set TG_TOKEN

mkdir -p data
.venv/bin/ryanair-bot
```

---

## Deployment (VPS)

```bash
# On your VPS
git clone https://github.com/andrebanandre/ryanair-telegram-bot
cd ryanair-telegram-bot
cp .env.example .env && nano .env   # set TG_TOKEN
mkdir -p data
docker compose up -d
```

To redeploy after an update:

```bash
git pull
docker compose up -d --build
```

---

## Project Structure

```
ryanair-telegram-bot/
├── bot/
│   ├── app.py              # Bot entry point, /start, /help, APScheduler setup
│   ├── common.py           # State constants, keyboard builders, result formatter
│   ├── wizard.py           # /search ConversationHandler (10 steps)
│   ├── query.py            # /find command handler
│   └── scheduler_conv.py   # /schedules ConversationHandler (CRUD)
├── flights.py              # Ryanair API wrapper (ryanair-py)
├── deals.py                # Deal detection logic
├── bot_history.py          # Price history persistence and trend calculation
├── chats.py                # Chat registry (chats.json)
├── schedules.py            # Schedule CRUD (schedules.json)
├── notify.py               # Push notification helper for CLI mode
└── main.py                 # CLI entry point (ryanair-telegram-bot)
Dockerfile
docker-compose.yml
```

---

## License

MIT License — see [LICENSE](LICENSE).

This project uses [ryanair-py](https://github.com/cohaesus/ryanair-py), an unofficial Ryanair API client. It is not affiliated with Ryanair.
