# T2-D2 — Robotic Trading Engine for Trading212 ISAs

> "Beep boop. Buy the dip." — T2-D2

A fully automated, schedule-driven DCA (Dollar Cost Averaging) trading bot for Trading212 ISAs, run locally from the command line. Monitors configured stock tickers across UK, US, and European markets — identifying downtrends and incrementally increasing positions within configurable risk thresholds.

---

## Architecture

```
t2-d2/
├── config/                  # Strategy, schedule, and stock configuration
├── packages/
│   ├── t2d2-client/         # Trading212 REST API client
│   ├── t2d2-market-data/    # Market data providers + trend analysis
│   └── t2d2-algo/           # Algorithm engine (mild → aggressive strategies)
└── services/
    └── scheduler/           # CLI entrypoint (run manually or via cron)
```

---

## Trading Logic

Each run:
1. Fetches available ISA cash balance from Trading212
2. Pulls daily + weekly OHLCV data for configured tickers
3. Analyses trend direction and magnitude per ticker
4. Applies each ticker's configured strategy (mild / moderate / aggressive) to determine if/how much to buy
5. Executes limit or market orders via Trading212 API
6. Logs each executed trade and a session summary, with a Trading212 instrument page link per trade (the pattern is only confirmed for US shares; UK/EU links are best guesses)

### Strategy Modes

| Mode       | Min Dip | Max Position Increase | Max Cash Deployed per Run |
|------------|---------|----------------------|--------------------------|
| mild       | -3%     | 5% of position       | 10% of available cash    |
| moderate   | -2%     | 10% of position      | 25% of available cash    |
| aggressive | -1%     | 20% of position      | 50% of available cash    |

---

## Schedules

Times are in each market's local time zone, so they follow daylight-saving changes. Source of truth: `config/schedules.yaml`.

| Session            | Runs (Mon–Fri)            | Purpose                          |
|--------------------|---------------------------|----------------------------------|
| `eu_morning`       | 08:30 Europe/London       | 30 min after London/Frankfurt open |
| `eu_afternoon`     | 15:30 Europe/London       | 1 hour before London/Frankfurt close |
| `us_morning`       | 10:00 America/New_York    | 30 min after NYSE/NASDAQ open    |
| `us_afternoon`     | 15:00 America/New_York    | 1 hour before NYSE/NASDAQ close  |
| `daily_close_wrap` | 17:00 America/New_York    | End-of-day summary (after US close) |

--------------------|---------------|----------------------------------|
| EU Morning Open    | `30 7 * * 1-5` | London/Frankfurt open (8:30 BST) |
| EU Afternoon       | `0 13 * * 1-5` | Mid-session rebalance            |
| US Morning Open    | `30 14 * * 1-5`| NYSE/NASDAQ open (9:30 ET)       |
| US Afternoon       | `30 18 * * 1-5`| US midday check (1:30 PM ET)     |
| EU/US Close Wrap   | `0 21 * * 1-5` | End-of-day summary               |

---

## Quick Start

### Prerequisites
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- Trading212 API key (live or demo)

### Local Setup

```bash
# Install Python workspace
uv sync --all-packages

# Copy and fill in secrets
cp .env.example .env

# Run a single trading cycle locally (dry-run)
uv run python -m scheduler.main --session eu_morning --dry-run

# Place real orders for this run only (overrides DRY_RUN=true in .env)
uv run python -m scheduler.main --session eu_morning --no-dry-run
```

`--dry-run` / `--no-dry-run` override `DRY_RUN` for a single run; with neither flag, `DRY_RUN`
decides (default `true`).

### Development

```bash
# Install and enable pre-commit hooks (run once after cloning)
uv sync
pre-commit install

# Hooks run automatically on commit: ruff, mypy, pytest
# To run manually against all files:
pre-commit run --all-files
```

### Running on a Schedule (Raspberry Pi / Linux)

See [install.md](install.md) for installing from GitHub with uv and running every session automatically with systemd timers.

---

## Telegram Notifications

Optional: get a Telegram message for every executed (or simulated) trade, with a link to the instrument.

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token it gives you.
2. Open your new bot and send it any message (bots can only message chats that have messaged them first).
3. Find your chat ID:

   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":[0-9-]*'
   ```

4. Add both to `.env`:

   ```bash
   TELEGRAM_BOT_TOKEN=<TOKEN>
   TELEGRAM_CHAT_ID=<CHAT_ID>
   ```

5. Send a test message:

   ```bash
   set -a; . ./.env; set +a
   curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" -d chat_id="$TELEGRAM_CHAT_ID" -d text="T2-D2 test"
   ```

A failed message is logged as `telegram_send_failed` and never stops the run. Leave either variable unset to turn notifications off.

---

## Configuration

See `config/` for:
- `stocks.yaml` — ticker lists by market; every ticker must set `strategy` (`mild` / `moderate` / `aggressive`)
- `strategy.yaml` — mode definitions and global risk limits
- `schedules.yaml` — which sessions are active and which markets they cover

---

## Environment Variables

| Variable                  | Description                                  |
|---------------------------|----------------------------------------------|
| `T212_API_KEY`            | Trading212 API key                           |
| `T212_BASE_URL`           | `https://live.trading212.com` or demo URL    |
| `DRY_RUN`                 | `true` (default) simulates without placing orders; `false` places real orders. Overridden by `--dry-run` / `--no-dry-run` |
| `TELEGRAM_BOT_TOKEN`      | Optional. Telegram bot token from @BotFather; with `TELEGRAM_CHAT_ID`, sends a message per executed trade |
| `TELEGRAM_CHAT_ID`        | Optional. Chat to send trade messages to (see [Telegram Notifications](#telegram-notifications)) |

---

## Disclaimer

This software is for personal educational use. Automated trading carries significant financial risk. Past performance of any strategy does not guarantee future results. Always understand and accept the risks before deploying with real money.
