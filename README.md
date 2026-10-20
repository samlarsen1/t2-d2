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
│   ├── t2d2-algo/           # Algorithm engine (mild → aggressive strategies)
│   └── t2d2-notifier/       # FCM push notifications + webhook dispatch
├── services/
│   └── scheduler/           # CLI entrypoint (run manually or via cron)
└── apps/
    └── android/             # Read-only Android app (Jetpack Compose + FCM)
```

---

## Trading Logic

Each run:
1. Fetches available ISA cash balance from Trading212
2. Pulls daily + weekly OHLCV data for configured tickers
3. Analyses trend direction and magnitude per ticker
4. Applies the configured strategy (mild / moderate / aggressive) to determine if/how much to buy
5. Executes limit or market orders via Trading212 API
6. Sends push notification to mobile app via Firebase Cloud Messaging

### Strategy Modes

| Mode       | Min Dip | Max Position Increase | Max Cash Deployed per Run |
|------------|---------|----------------------|--------------------------|
| mild       | -3%     | 5% of position       | 10% of available cash    |
| moderate   | -2%     | 10% of position      | 25% of available cash    |
| aggressive | -1%     | 20% of position      | 50% of available cash    |

---

## Schedules (UTC)

| Window             | Cron (UTC)    | Purpose                          |
|--------------------|---------------|----------------------------------|
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
- Firebase project (optional, for push notifications)

### Local Setup

```bash
# Install Python workspace
uv sync --all-packages

# Copy and fill in secrets
cp .env.example .env

# Run a single trading cycle locally (dry-run)
uv run python -m scheduler.main --session eu_morning --dry-run
```

### Development

```bash
# Install and enable pre-commit hooks (run once after cloning)
uv sync
pre-commit install

# Hooks run automatically on commit: ruff, mypy, pytest
# To run manually against all files:
pre-commit run --all-files
```

### Scheduling Locally (cron)

Add entries to your crontab (`crontab -e`) matching the session times above. Times are UTC, so set `CRON_TZ=UTC` (or convert to your local time):

```cron
CRON_TZ=UTC
30 7  * * 1-5  cd /path/to/t2-d2 && .venv/bin/python services/scheduler/src/scheduler/main.py --session eu_morning       >> logs/scheduler.log 2>&1
0  13 * * 1-5  cd /path/to/t2-d2 && .venv/bin/python services/scheduler/src/scheduler/main.py --session eu_afternoon     >> logs/scheduler.log 2>&1
30 14 * * 1-5  cd /path/to/t2-d2 && .venv/bin/python services/scheduler/src/scheduler/main.py --session us_morning       >> logs/scheduler.log 2>&1
30 18 * * 1-5  cd /path/to/t2-d2 && .venv/bin/python services/scheduler/src/scheduler/main.py --session us_afternoon     >> logs/scheduler.log 2>&1
0  21 * * 1-5  cd /path/to/t2-d2 && .venv/bin/python services/scheduler/src/scheduler/main.py --session daily_close_wrap >> logs/scheduler.log 2>&1
```

Create the log directory first with `mkdir -p logs` (it is gitignored). Runs are dry-run unless `.env` sets `DRY_RUN=false`.

---

## Configuration

See `config/` for:
- `stocks.yaml` — ticker lists by market with per-ticker overrides
- `strategy.yaml` — mode definitions and global risk limits
- `schedules.yaml` — which sessions are active and which markets they cover

---

## Android App

The companion app is read-only and shows:
- Current portfolio positions and P&L
- Recent trades executed by T2-D2
- Push notifications for each trade

Runs on Pixel phones and Chromebooks (ChromeOS Play Store).

---

## Environment Variables

| Variable                  | Description                                  |
|---------------------------|----------------------------------------------|
| `T212_API_KEY`            | Trading212 API key                           |
| `T212_BASE_URL`           | `https://live.trading212.com` or demo URL    |
| `FIREBASE_CREDENTIALS`    | Path to Firebase service account JSON        |
| `FCM_TOPIC`               | FCM topic for broadcast pushes               |
| `STRATEGY_MODE`           | `mild` / `moderate` / `aggressive`           |
| `DRY_RUN`                 | `true` to simulate without placing orders    |

---

## Disclaimer

This software is for personal educational use. Automated trading carries significant financial risk. Past performance of any strategy does not guarantee future results. Always understand and accept the risks before deploying with real money.
