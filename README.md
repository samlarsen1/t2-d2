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
4. Applies each ticker's configured strategy (deep_value / mild / moderate / aggressive) to determine if/how much to buy
5. Executes limit or market orders via Trading212 API
6. Logs each executed trade and a session summary, with a Trading212 instrument page link per trade (the pattern is only confirmed for US shares; UK/EU links are best guesses)

### Strategy Modes

| Mode       | Min Dip | Max Position Increase | Max Cash Deployed per Run |
|------------|---------|----------------------|--------------------------|
| deep_value | long-term downtrend (see below) | 3% of position | 3% of available cash |
| mild       | -3%     | 5% of position       | 10% of available cash    |
| moderate   | -2%     | 10% of position      | 25% of available cash    |
| aggressive | -1%     | 20% of position      | 50% of available cash    |

`deep_value` ignores daily dips (its `trigger` is `long_term_downtrend`). It buys only when a stock is
within 2% of its 52-week closing low, or has fallen at least 20% over the last quarter (~63 trading
days) or 30% over the last half year (~126 trading days) and is still below its 50-day SMA. The RSI
gate and the other risk limits still apply. Its tickers are evaluated only in the weekly
`deep_value_midweek` session, Wednesdays at 15:15 London time while the EU and US markets are both
open (`trade_weekday` / `trade_sessions` in `strategy.yaml`); if the UK or US market is closed that
Wednesday, the week is skipped. These tickers fetch a year of prices, and a ticker
listed for less than a year never counts as being at its 52-week low. When `max_trades_per_run`
caps the buys, `deep_value` buys are ranked by their quarter or half-year fall (whichever is deeper),
so a long slide isn't pushed out because the stock happens to be up that day.

---

## Schedules

Times are in each market's local time zone, so they follow daylight-saving changes. Source of truth: `config/schedules.yaml`.

| Session            | Runs (Mon–Fri)            | Purpose                          |
|--------------------|---------------------------|----------------------------------|
| `eu_morning`       | 08:30 Europe/London       | 30 min after London/Frankfurt open |
| `eu_afternoon`     | 15:30 Europe/London       | 1 hour before London/Frankfurt close |
| `us_morning`       | 10:00 America/New_York    | 30 min after NYSE/NASDAQ open    |
| `us_afternoon`     | 15:00 America/New_York    | 1 hour before NYSE/NASDAQ close  |
| `deep_value_midweek` | Wed only, 15:15 Europe/London | `deep_value` tickers only; ≥45 min after NYSE open, 75 min before London/Frankfurt close |
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

# Hooks run automatically on commit: detect-secrets, ruff, bandit, semgrep, pip-audit, mypy, pytest,
# plus a branch name check (see Branch naming below)
# To run manually against all files:
pre-commit run --all-files
```

#### Branch naming

Commit on a branch named after the type of change, in lowercase with hyphens:

| Pattern | Use for |
|---------|---------|
| `feature/<name>` | New behaviour |
| `bug/<name>` | Fixes |
| `task/<name>` | Everything else: config, docs, dependencies, CI |
| `hotfix/<name>` | Urgent fixes |
| `dependabot/...` | Created by Dependabot, so `<name>` doesn't need to be lowercase-with-hyphens |

```bash
git switch -c feature/min-trade-floor
```

The `branch-name` hook rejects commits on any other branch, including `main`. If you installed the
hooks before this check was added, run `pre-commit install` again to enable it.

GitHub enforces the same convention with these rulesets:

| Ruleset | Applies to | Rules |
|---------|------------|-------|
| `main` | `main` | Requires a pull request and the `Branch name` check, so only branches following the patterns above can merge. Also requires CodeQL results, blocks deletion and force-pushes, and requests a Copilot review |
| `branches` | `feature/**`, `bug/**`, `task/**`, `hotfix/**` | Blocks force-pushes; deletion is allowed. `dependabot/**` is left out because Dependabot force-pushes when it rebases its branches |
| `branch-naming` | Everything else | Blocks creating the branch |

Branches are deleted from GitHub automatically after merging. `branch-naming` only checks the
prefix, so a name like `task/Bad_Name` can be pushed, but the `Branch name` check stops it merging.
It also excludes `dependabot/**/*` as well as `dependabot/**`, because a trailing `**` doesn't match
further slashes and Dependabot's names have them (`dependabot/pip/foo-1.2.3`).

```bash
# Show which rules apply to a branch name
gh api repos/samlarsen1/t2-d2/rules/branches/task/my-change --jq '.[].type'
```

#### Vulnerability scanning

These hooks block the commit on any finding:

| Hook | Checks | Runs when |
|------|--------|-----------|
| `bandit` | Insecure Python patterns, medium severity and above (config in `pyproject.toml`) | Python files change |
| `semgrep` | Semgrep's OWASP Top 10 and Python rulesets, fetched from its registry (needs network) | Any file changes |
| `pip-audit` | Every package in `uv.lock` against known advisories (needs network) | Every commit |

```bash
# Run one scanner on its own
pre-commit run bandit --all-files
pre-commit run semgrep --all-files
pre-commit run pip-audit --all-files

# Fix a vulnerable dependency, then re-run pip-audit
uv lock --upgrade-package <package>
uv sync
```

`pip-audit` runs on every commit, so a newly published advisory blocks all commits until the package
is upgraded. The [Dependency Audit](.github/workflows/dependency-audit.yml) workflow also runs it
daily on GitHub Actions to catch advisories on days with no commits. To trigger it manually:

```bash
gh workflow run dependency-audit.yml
```

`uv` also ignores package versions published in the last 7 days
(`exclude-newer` in `pyproject.toml`), so a very recent fix may need a short wait. If the fix is too
new, or you're offline, commit with `SKIP=pip-audit git commit` and upgrade once you can. Semgrep
blocks any shorter cooldown (`uv-missing-dependency-cooldown`).

Dependabot checks weekly for newer GitHub Actions versions and opens a pull request for each one
(config in `.github/dependabot.yml`). It keeps them pinned to commit SHAs and skips versions published
in the last 7 days. It doesn't cover Python packages: upgrade those with `uv lock` and rely on
`pip-audit` to flag vulnerable ones.

### Running on a Schedule (Raspberry Pi / Linux)

See [install.md](install.md) for installing from GitHub with uv and running every session automatically with systemd timers.

---

## Telegram Notifications

Optional: get a Telegram message for every executed (or simulated) trade, with a link to the instrument. A session that places no trades sends a single "no trades today" message instead, a session that cancels expired limit orders lists them in a separate message, and `daily_close_wrap` sends a portfolio summary (cash, invested value, positions, orders filled today).

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
- `stocks.yaml` — ticker lists by market; every ticker must set `strategy` (`deep_value` / `mild` / `moderate` / `aggressive`)
- `strategy.yaml` — mode definitions and global risk limits, including `min_trade_floor_gbp`, which raises any smaller percentage-based trade to that amount without touching `min_cash_reserve_gbp`, and `limit_order_expiry_days`, the age at which the bot cancels its own unfilled limit buy orders. Limit orders are placed as good-till-cancel because Trading212 has no expiry date option, so expiry happens at the next trading session after that age. Orders placed by hand are never cancelled, and a ticker with an open order isn't bought again until that order fills or is cancelled.
- `schedules.yaml` — which sessions are active and which markets they cover; a session's optional `strategies` list limits it to tickers on those strategies (e.g. `deep_value_midweek` only runs `deep_value`)

---

## Environment Variables

| Variable                  | Description                                  |
|---------------------------|----------------------------------------------|
| `T212_API_KEY`            | Trading212 API key                           |
| `T212_BASE_URL`           | `https://live.trading212.com` or demo URL    |
| `DRY_RUN`                 | `true` (default) simulates without placing orders; `false` places real orders. Overridden by `--dry-run` / `--no-dry-run` |
| `TELEGRAM_BOT_TOKEN`      | Optional. Telegram bot token from @BotFather; with `TELEGRAM_CHAT_ID`, sends a message per executed trade (or "no trades today") and a daily wrap summary |
| `TELEGRAM_CHAT_ID`        | Optional. Chat to send trade messages to (see [Telegram Notifications](#telegram-notifications)) |

---

## Disclaimer

This software is for personal educational use. Automated trading carries significant financial risk. Past performance of any strategy does not guarantee future results. Always understand and accept the risks before deploying with real money.
