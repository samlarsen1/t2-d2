"""
T2-D2 Scheduler — local CLI entrypoint.

Run manually or from cron at configured session times.
Orchestrates the full trading cycle:
  1. Validate session / blackout date check
  2. Fetch account cash + positions
  3. Pull market data for configured tickers
  4. Run algo engine to generate decisions
  5. Execute trades (or dry-run)
  6. Log executed trades and a session summary
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
import yaml
from dotenv import load_dotenv
from t2d2_algo import AlgoEngine, RunResult, TradeExecutor, load_strategy_configs
from t2d2_algo.strategies.base import TradeDecision
from t2d2_client import Trading212Client
from t2d2_client.models import OrderStatus
from t2d2_market_data import TrendAnalyser, YahooFinanceProvider

load_dotenv()

# Root of the repository
REPO_ROOT = Path(__file__).parents[4]
CONFIG_DIR = REPO_ROOT / "config"

log = structlog.get_logger()


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
    )


def load_stocks_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "stocks.yaml") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def load_schedules_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "schedules.yaml") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def is_blackout(session_cfg: dict[str, Any], markets: list[str]) -> bool:
    """Return True if today is a blackout date for any of the session's markets."""
    schedules = load_schedules_config()
    blackouts = schedules.get("blackout_dates", {})
    today = date.today().isoformat()
    for market in markets:
        if today in blackouts.get(market, []):
            log.info("blackout_date", market=market, date=today)
            return True
    return False


def validate_stock_strategies(stocks: dict[str, Any], strategies: set[str]) -> None:
    """Check every traded ticker in stocks.yaml names a known strategy.

    Args:
        stocks: Parsed stocks.yaml.
        strategies: Strategy mode names defined in strategy.yaml.

    Raises:
        ValueError: If any ticker has no ``strategy`` or an unknown one.
    """
    problems: list[str] = []
    for market, market_cfg in stocks.get("markets", {}).items():
        for ticker_entry in market_cfg.get("tickers", []):
            strategy = ticker_entry.get("strategy")
            label = f"{market}/{ticker_entry.get('symbol', '?')}"
            if strategy is None:
                problems.append(f"{label}: missing 'strategy'")
            elif strategy not in strategies:
                problems.append(f"{label}: unknown strategy {strategy!r}")
    if problems:
        raise ValueError(
            f"Invalid stocks.yaml (valid strategies: {', '.join(sorted(strategies))}): "
            + "; ".join(problems)
        )


def get_tickers_for_session(
    stocks: dict[str, Any], markets: list[str]
) -> list[tuple[str, str, str, str]]:
    """Return [(symbol, t212_ticker, market, strategy)] for the given markets."""
    result = []
    for market in markets:
        market_cfg = stocks.get("markets", {}).get(market, {})
        for ticker_entry in market_cfg.get("tickers", []):
            symbol = ticker_entry["symbol"]
            t212_ticker = ticker_entry.get("t212_ticker", symbol)
            result.append((symbol, t212_ticker, market, ticker_entry["strategy"]))
    return result


async def run_trading_cycle(session: str, dry_run: bool) -> RunResult:
    api_key = os.environ["T212_API_KEY"]
    api_secret = os.environ["T212_API_SECRET"]
    base_url = os.getenv("T212_BASE_URL", "https://live.trading212.com")

    schedules = load_schedules_config()
    session_cfg = schedules["sessions"].get(session)
    if not session_cfg:
        raise ValueError(f"Unknown session: {session}")

    if not session_cfg.get("enabled", True):
        log.info("session_disabled", session=session)
        return RunResult(session=session, available_cash_gbp=0.0)

    markets: list[str] = session_cfg["markets"]
    action: str = session_cfg.get("action", "trade")

    if is_blackout(session_cfg, markets):
        log.info("skipping_blackout", session=session)
        return RunResult(session=session, available_cash_gbp=0.0)

    strategy_configs = load_strategy_configs(CONFIG_DIR)
    stocks_cfg = load_stocks_config()
    validate_stock_strategies(stocks_cfg, set(strategy_configs))
    engines = {mode: AlgoEngine(cfg) for mode, cfg in strategy_configs.items()}
    # Global limits and analysis settings are the same in every mode's config
    shared_config = next(iter(strategy_configs.values()))

    async with Trading212Client(api_key=api_key, api_secret=api_secret, base_url=base_url) as client:  # noqa: E501
        # Fetch account state
        summary = await client.get_account_summary()
        positions = await client.get_positions()
        available_cash = float(summary.cash.available_to_trade)
        invested = float(summary.investments.current_value)
        total_portfolio = invested + available_cash

        log.info(
            "account_state",
            free_cash=available_cash,
            invested=invested,
            positions=len(positions),
        )

        result = RunResult(
            session=session,
            available_cash_gbp=available_cash,
            dry_run=dry_run,
        )

        # Report-only sessions
        if action == "report":
            log.info("session_report", session=session, cash_remaining_gbp=available_cash)
            return result

        # Fetch market data for session tickers
        tickers = get_tickers_for_session(stocks_cfg, markets)
        log.info("fetching_market_data", ticker_count=len(tickers), session=session)

        provider = YahooFinanceProvider()
        period_days = max(
            shared_config.daily_lookback_days,
            shared_config.weekly_lookback_days,
        ) + 5  # buffer

        # Build cooldown set from recent order history + pending orders
        t212_to_symbol = {t212: sym for sym, t212, _, _ in tickers}
        cooldown_cutoff = datetime.now(tz=UTC) - timedelta(
            hours=shared_config.ticker_cooldown_hours
        )
        _skip_statuses = {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.CANCELLING}
        recently_traded: set[str] = set()

        # Check order history (may be unavailable on demo accounts)
        try:
            recent_orders = await client.get_order_history(limit=50)
            recently_traded |= {
                t212_to_symbol[o.ticker]
                for o in recent_orders
                if o.ticker in t212_to_symbol
                and o.creation_time is not None
                and o.creation_time >= cooldown_cutoff
                and o.status not in _skip_statuses
            }
        except Exception as e:
            log.warning("order_history_unavailable", error_type=type(e).__name__)

        # Also check pending orders (catches limit orders not yet filled)
        pending_orders = await client.get_all_orders()
        recently_traded |= {
            t212_to_symbol[o.ticker]
            for o in pending_orders
            if o.ticker in t212_to_symbol
            and o.creation_time is not None
            and o.creation_time >= cooldown_cutoff
            and o.status not in _skip_statuses
        }

        if recently_traded:
            log.info(
                "cooldown_active",
                tickers=sorted(recently_traded),
                hours=shared_config.ticker_cooldown_hours,
            )

        yahoo_tickers = [(symbol, market) for symbol, _t212, market, _strategy in tickers]
        ohlcv_data = await provider.fetch_multiple(yahoo_tickers, period_days=period_days)
        analyser = TrendAnalyser()
        signals = analyser.analyse_many(ohlcv_data)
        quote_currencies = {sig.currency for sig in signals.values() if sig.currency}
        fx_rates = await provider.fetch_fx_rates_async(quote_currencies, summary.currency)
        log.info("fx_rates", account_currency=summary.currency, **fx_rates)

        log.info("signals_computed", count=len(signals))

        # Build position lookup by T212 ticker
        position_map = {p.ticker: p for p in positions}

        # Evaluate each signal with the ticker's own strategy
        decisions: list[TradeDecision] = []

        for symbol, t212_ticker, _market, strategy in tickers:
            if symbol not in signals:
                log.warning("no_signal", ticker=symbol)
                continue

            signal = signals[symbol]
            position = position_map.get(t212_ticker)

            decision = engines[strategy].evaluate(
                signal=signal,
                position=position,
                available_cash=available_cash,
                total_portfolio_value=total_portfolio,
                fx_rate=fx_rates.get(signal.currency) if signal.currency else None,
                recently_traded=recently_traded,
            )
            decision.t212_ticker = t212_ticker
            decisions.append(decision)
            log.debug(
                "decision",
                ticker=symbol,
                strategy=strategy,
                trade=decision.should_trade,
                reason=decision.reason,
            )

        result.decisions = decisions

        # Rank and cap
        ranked = AlgoEngine(shared_config).rank_decisions(decisions)
        log.info("ranked_trades", count=len(ranked))

        # Execute
        executor = TradeExecutor(client=client, dry_run=dry_run)

        for decision in ranked:
            success = await executor.execute(decision)
            if success:
                result.executed_trades.append(decision)
                available_cash -= decision.trade_value_gbp

                log.info(
                    "trade_executed",
                    ticker=decision.ticker,
                    strategy=decision.strategy,
                    action="BUY",
                    value_gbp=round(decision.trade_value_gbp, 2),
                    price=decision.current_price,
                    limit_price=decision.limit_price,
                    quantity=decision.quantity,
                    currency=decision.currency,
                    daily_change_pct=round(decision.daily_change_pct, 2),
                    weekly_change_pct=round(decision.weekly_change_pct, 2),
                    dry_run=dry_run,
                )

        log.info("run_complete", **{
            "session": session,
            "trades": len(result.executed_trades),
            "deployed_gbp": result.total_deployed_gbp,
            "cash_remaining_gbp": available_cash,
        })

    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    ``--dry-run`` / ``--no-dry-run`` override the ``DRY_RUN`` env var, which
    defaults to true when unset.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Parsed arguments with ``session`` and ``dry_run``.
    """
    parser = argparse.ArgumentParser(description="T2-D2 Trading Scheduler")
    parser.add_argument(
        "--session",
        required=True,
        choices=["eu_morning", "eu_afternoon", "us_morning", "us_afternoon", "daily_close_wrap"],
        help="Trading session to run",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("DRY_RUN", "true").lower() == "true",
        help="Simulate trades without placing orders (default: $DRY_RUN, else true)",
    )
    return parser.parse_args(argv)


def main() -> None:
    setup_logging()
    args = parse_args()

    log.info("t2d2_starting", session=args.session, dry_run=args.dry_run)

    result = asyncio.run(run_trading_cycle(args.session, args.dry_run))
    print(result.summary())

    if result.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
