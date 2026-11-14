"""
T2-D2 Scheduler — local CLI entrypoint.

Run manually or from cron at configured session times.
Orchestrates the full trading cycle:
  1. Validate session / blackout date check
  2. Fetch account cash + positions
  3. Pull market data for configured tickers
  4. Run algo engine to generate decisions
  5. Execute trades (or dry-run)
  6. Log executed trades and a session summary; notify Telegram per trade
     (or that there were none) if configured
  7. Report-only sessions (daily_close_wrap) send a portfolio summary to Telegram
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
from t2d2_algo.strategies.base import StrategyConfig, TradeDecision
from t2d2_client import Trading212Client
from t2d2_client.models import HistoricalOrder, Order, OrderStatus, OrderType
from t2d2_market_data import TrendAnalyser, YahooFinanceProvider

from scheduler.telegram import (
    TelegramNotifier,
    format_cancelled_orders_message,
    format_daily_wrap_message,
    format_no_trades_message,
    format_trade_message,
)

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


def validate_strategy_sessions(
    strategy_configs: dict[str, StrategyConfig], sessions: set[str]
) -> None:
    """Check every strategy's ``trade_sessions`` names a session in schedules.yaml.

    Args:
        strategy_configs: Strategy modes from strategy.yaml.
        sessions: Session names defined in schedules.yaml.

    Raises:
        ValueError: If any strategy names an unknown session.
    """
    problems = [
        f"{mode}: unknown session {name!r}"
        for mode, cfg in strategy_configs.items()
        for name in cfg.trade_sessions or []
        if name not in sessions
    ]
    if problems:
        raise ValueError("Invalid strategy.yaml trade_sessions: " + "; ".join(problems))


def validate_session_strategies(
    sessions: dict[str, dict[str, Any]], strategies: set[str]
) -> None:
    """Check every session's optional ``strategies`` list names known strategy modes.

    Args:
        sessions: The ``sessions`` mapping from schedules.yaml.
        strategies: Strategy mode names defined in strategy.yaml.

    Raises:
        ValueError: If any session names an unknown strategy.
    """
    problems = [
        f"{session}: unknown strategy {name!r}"
        for session, session_cfg in sessions.items()
        for name in session_cfg.get("strategies") or []
        if name not in strategies
    ]
    if problems:
        raise ValueError("Invalid schedules.yaml strategies: " + "; ".join(problems))


def active_tickers(
    tickers: list[tuple[str, str, str, str]],
    strategy_configs: dict[str, StrategyConfig],
    session: str,
    today: date,
    session_strategies: list[str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Drop tickers whose strategy doesn't run in this session on this day.

    Args:
        tickers: ``[(symbol, t212_ticker, market, strategy)]`` for the session.
        strategy_configs: Strategy modes from strategy.yaml.
        session: Session being run.
        today: Date of the run.
        session_strategies: The session's ``strategies`` list from schedules.yaml; when set,
            tickers on any other strategy are dropped.

    Returns:
        The tickers to evaluate, in their original order.
    """
    return [
        t
        for t in tickers
        if (session_strategies is None or t[3] in session_strategies)
        and strategy_configs[t[3]].is_active(session, today)
    ]


def history_days(config: StrategyConfig, buffer_days: int = 5) -> int:
    """Return how many days of prices to fetch for a strategy's tickers.

    Modes with the rising-trend-SMA gate need enough trading days for it (200 + 20 by
    default); long-term modes need a full year. Trading days are converted to calendar
    days, with ~4% extra for exchange holidays, so enough rows survive weekends and holidays.

    Args:
        config: The ticker's strategy.
        buffer_days: Extra days on top of the longest lookback.
    """
    trading_days = max(config.daily_lookback_days, config.weekly_lookback_days)
    if config.require_rising_trend_sma:
        trading_days = max(trading_days, config.trend_history_days)
    if config.needs_long_history:
        trading_days = max(trading_days, config.year_lookback_days)
    return int(trading_days) * 365 // 252 + int(trading_days) // 25 + buffer_days


INACTIVE_ORDER_STATUSES = {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.CANCELLING}


def start_of_today_utc() -> datetime:
    """Return midnight UTC at the start of the current day."""
    return datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def count_filled_orders_since(orders: list[HistoricalOrder], cutoff: datetime) -> int:
    """Count fully or partially filled orders filled at or after ``cutoff``.

    Orders with no fill time fall back to their creation time.

    Args:
        orders: Order history from Trading212.
        cutoff: Earliest time to include (timezone-aware).

    Returns:
        Number of matching orders.
    """
    filled = {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}
    return sum(
        1
        for o in orders
        if o.status in filled
        and (traded_at := o.filled_at or o.creation_time) is not None
        and traded_at >= cutoff
    )


def find_expired_limit_orders(orders: list[Order], cutoff: datetime) -> list[Order]:
    """Find the bot's own limit buy orders created before ``cutoff``.

    Only orders placed through the API qualify, so orders placed by hand in the
    Trading212 app are never returned.

    Args:
        orders: Pending orders from Trading212.
        cutoff: Orders created before this time have expired (timezone-aware).

    Returns:
        The expired orders.
    """
    return [
        o
        for o in orders
        if o.type == OrderType.LIMIT
        and o.side == "BUY"
        and o.initiated_from == "API"
        and o.status not in INACTIVE_ORDER_STATUSES
        and o.creation_time is not None
        and o.creation_time < cutoff
    ]


async def cancel_expired_limit_orders(
    client: Trading212Client, orders: list[Order], expiry_days: int, dry_run: bool
) -> list[Order]:
    """Cancel expired limit orders, logging any failure so the run can continue.

    Args:
        client: Trading212 API client.
        orders: Pending orders from Trading212.
        expiry_days: Age in days at which a limit order expires.
        dry_run: Log what would be cancelled without cancelling it.

    Returns:
        The orders cancelled, or that would have been in a dry run.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(days=expiry_days)
    cancelled: list[Order] = []
    for order in find_expired_limit_orders(orders, cutoff):
        if order.id is None:
            log.warning("expired_order_without_id", ticker=order.ticker)
            continue
        if dry_run:
            log.info("expired_order_not_cancelled_dry_run", ticker=order.ticker, order_id=order.id)
            cancelled.append(order)
            continue
        try:
            await client.cancel_order(order.id)
            log.info("expired_order_cancelled", ticker=order.ticker, order_id=order.id)
            cancelled.append(order)
        except Exception as e:
            log.warning(
                "expired_order_cancel_failed",
                ticker=order.ticker,
                order_id=order.id,
                error_type=type(e).__name__,
            )
    return cancelled


def tickers_with_open_orders(orders: list[Order], t212_to_symbol: dict[str, str]) -> set[str]:
    """Return the symbols with an open order, however old, so orders don't stack up.

    Args:
        orders: Pending orders from Trading212.
        t212_to_symbol: Mapping of Trading212 ticker to symbol for this session.

    Returns:
        Symbols that shouldn't be bought again yet.
    """
    return {
        t212_to_symbol[o.ticker]
        for o in orders
        if o.ticker in t212_to_symbol and o.status not in INACTIVE_ORDER_STATUSES
    }


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
    validate_strategy_sessions(strategy_configs, set(schedules["sessions"]))
    validate_session_strategies(schedules["sessions"], set(strategy_configs))
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
            report_notifier = TelegramNotifier.from_env()
            if report_notifier:
                orders_filled_today: int | None = None
                try:
                    history = await client.get_order_history(limit=50)
                    orders_filled_today = count_filled_orders_since(history, start_of_today_utc())
                except Exception as e:
                    log.warning("order_history_unavailable", error_type=type(e).__name__)
                await report_notifier.send(
                    format_daily_wrap_message(
                        available_cash, invested, len(positions), orders_filled_today
                    )
                )
            return result

        # Fetch market data for the session's tickers whose strategy runs today
        all_tickers = get_tickers_for_session(stocks_cfg, markets)
        tickers = active_tickers(
            all_tickers,
            strategy_configs,
            session,
            date.today(),
            session_strategies=session_cfg.get("strategies"),
        )
        if len(tickers) < len(all_tickers):
            log.info(
                "tickers_inactive_today",
                tickers=sorted({t[0] for t in all_tickers} - {t[0] for t in tickers}),
            )
        log.info("fetching_market_data", ticker_count=len(tickers), session=session)

        provider = YahooFinanceProvider()

        # Build cooldown set from recent order history + pending orders
        t212_to_symbol = {t212: sym for sym, t212, _, _ in tickers}
        cooldown_cutoff = datetime.now(tz=UTC) - timedelta(
            hours=shared_config.ticker_cooldown_hours
        )
        recently_traded: set[str] = set()

        # Check order history (may be unavailable on demo accounts)
        try:
            recent_orders = await client.get_order_history(limit=50)
            recently_traded |= {
                t212_to_symbol[o.ticker]
                for o in recent_orders
                if o.ticker in t212_to_symbol
                and (traded_at := o.filled_at or o.creation_time) is not None
                and traded_at >= cooldown_cutoff
                and o.status not in INACTIVE_ORDER_STATUSES
            }
        except Exception as e:
            log.warning("order_history_unavailable", error_type=type(e).__name__)

        # Also check pending orders (catches limit orders not yet filled). An order cancelled
        # here still blocks this run: the cash figure above doesn't include its released funds.
        pending_orders = await client.get_all_orders()
        recently_traded |= tickers_with_open_orders(pending_orders, t212_to_symbol)
        cancelled_orders = await cancel_expired_limit_orders(
            client, pending_orders, shared_config.limit_order_expiry_days, dry_run
        )
        notifier = TelegramNotifier.from_env()
        if notifier and cancelled_orders:
            await notifier.send(format_cancelled_orders_message(cancelled_orders, session, dry_run))

        if recently_traded:
            log.info(
                "cooldown_active",
                tickers=sorted(recently_traded),
                hours=shared_config.ticker_cooldown_hours,
            )

        # Long-term strategies need a year of prices, the rest enough for the trend SMA
        # slope; fetch each history length separately
        by_period: dict[int, list[tuple[str, str]]] = {}
        for symbol, _t212, market, strategy in tickers:
            period = history_days(strategy_configs[strategy])
            by_period.setdefault(period, []).append((symbol, market))
        analyser = TrendAnalyser(
            quarter_days=shared_config.quarter_lookback_days,
            half_year_days=shared_config.half_year_lookback_days,
            year_days=shared_config.year_lookback_days,
            trend_sma_days=shared_config.trend_sma_days,
            trend_slope_days=shared_config.trend_slope_days,
        )
        signals = {}
        for period, yahoo_tickers in by_period.items():
            ohlcv_data = await provider.fetch_multiple(yahoo_tickers, period_days=period)
            signals.update(analyser.analyse_many(ohlcv_data))
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
        shared_engine = AlgoEngine(shared_config)
        ranked = shared_engine.rank_decisions(decisions)
        log.info("ranked_trades", count=len(ranked))

        # Execute
        executor = TradeExecutor(client=client, dry_run=dry_run)

        for decision in ranked:
            if not shared_engine.preserves_cash_reserve(decision, available_cash):
                log.warning(
                    "trade_skipped_cash_reserve",
                    ticker=decision.ticker,
                    value_gbp=round(decision.trade_value_gbp, 2),
                    cash_remaining_gbp=available_cash,
                )
                continue

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
                if notifier:
                    await notifier.send(format_trade_message(decision, session, dry_run))

        if notifier and not result.executed_trades:
            await notifier.send(format_no_trades_message(session, dry_run))

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
        choices=[
            "eu_morning",
            "eu_afternoon",
            "us_morning",
            "us_afternoon",
            "deep_value_midweek",
            "daily_close_wrap",
        ],
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
