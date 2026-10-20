"""
T2-D2 Algorithm Engine.

Evaluates trend signals against strategy config to produce TradeDecisions,
then executes orders via the Trading212 client.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import yaml
from t2d2_client import Position, Trading212Client
from t2d2_client.models import TimeValidity
from t2d2_market_data.analysis import TrendSignal

from .strategies.base import StrategyConfig, TradeDecision

logger = logging.getLogger(__name__)

# Limit prices are sent to 2 decimal places in the quote currency (cents, pence)
LIMIT_PRICE_DECIMALS = 2
QUANTITY_DECIMALS = 4


def _round_down(value: float, decimals: int) -> float:
    """Round towards zero so a buy never exceeds its budget or target price."""
    step = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(step, rounding=ROUND_DOWN))


@dataclass
class RunResult:
    session: str
    available_cash_gbp: float
    decisions: list[TradeDecision] = field(default_factory=list)
    executed_trades: list[TradeDecision] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def total_deployed_gbp(self) -> float:
        return sum(t.trade_value_gbp for t in self.executed_trades)

    def summary(self) -> str:
        lines = [
            f"=== T2-D2 Run: {self.session} ===",
            f"Available cash: £{self.available_cash_gbp:.2f}",
            f"Decisions evaluated: {len(self.decisions)}",
            f"Trades {'simulated' if self.dry_run else 'executed'}: {len(self.executed_trades)}",
            f"Capital deployed: £{self.total_deployed_gbp:.2f}",
        ]
        if self.executed_trades:
            lines.append("\nTrades:")
            for t in self.executed_trades:
                lines.append(f"  {t}")
        if self.errors:
            lines.append("\nErrors:")
            for e in self.errors:
                lines.append(f"  ! {e}")
        return "\n".join(lines)


def load_strategy_configs(config_dir: Path) -> dict[str, StrategyConfig]:
    """Load every strategy mode defined in ``strategy.yaml``.

    Args:
        config_dir: Directory containing ``strategy.yaml``.

    Returns:
        Mapping of mode name (e.g. ``"mild"``) to its config. Global limits and
        analysis settings are shared, so they are identical in every entry.
    """
    strategy_path = config_dir / "strategy.yaml"
    with open(strategy_path) as f:
        raw = yaml.safe_load(f)

    global_cfg = raw["global_limits"]
    analysis_cfg = raw["analysis"]

    return {
        mode: StrategyConfig(
            mode=mode,
            min_daily_dip_pct=mode_cfg["min_daily_dip_pct"],
            min_weekly_dip_pct=mode_cfg.get("min_weekly_dip_pct"),
            max_position_increase_pct=mode_cfg["max_position_increase_pct"],
            max_cash_deploy_pct=mode_cfg["max_cash_deploy_pct"],
            order_type=mode_cfg["order_type"],
            limit_discount_pct=mode_cfg["limit_discount_pct"],
            max_portfolio_weight_pct=mode_cfg["max_portfolio_weight_pct"],
            min_trade_gbp=mode_cfg["min_trade_gbp"],
            absolute_max_cash_deploy_pct=global_cfg["absolute_max_cash_deploy_pct"],
            min_cash_reserve_gbp=global_cfg["min_cash_reserve_gbp"],
            max_trades_per_run=global_cfg["max_trades_per_run"],
            ticker_cooldown_hours=global_cfg["ticker_cooldown_hours"],
            rsi_max_buy=analysis_cfg["rsi_max_buy"],
            daily_lookback_days=analysis_cfg["daily_lookback_days"],
            weekly_lookback_days=analysis_cfg["weekly_lookback_days"],
            require_both_timeframes=mode_cfg.get("require_both_timeframes", False),
        )
        for mode, mode_cfg in raw["modes"].items()
    }


class AlgoEngine:
    """Core decision-making engine."""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def evaluate(
        self,
        signal: TrendSignal,
        position: Position | None,
        available_cash: float,
        total_portfolio_value: float,
        fx_rate: float | None,
        recently_traded: set[str] | None = None,
    ) -> TradeDecision:
        """
        Evaluate a single ticker's signal and decide whether to trade.

        Args:
            signal: Trend data for the ticker.
            position: Current held position (None if not held).
            available_cash: Free ISA cash in account currency.
            total_portfolio_value: Total invested + cash.
            fx_rate: Quote-currency units per one unit of account currency, e.g. 100
                for a GBp (pence) quote in a GBP account, or 1.34 for USD. None if
                unknown, in which case the ticker is skipped.
            recently_traded: Tickers still in their post-trade cooldown.
        """
        cfg = self.config
        ticker = signal.ticker

        min_daily = cfg.min_daily_dip_pct
        max_cash_pct = cfg.max_cash_deploy_pct / 100

        def skip(reason: str) -> TradeDecision:
            return TradeDecision(
                ticker=ticker,
                should_trade=False,
                trade_value_gbp=0.0,
                reason=reason,
                daily_change_pct=signal.daily_change_pct,
                weekly_change_pct=signal.weekly_change_pct,
                rsi=signal.rsi,
                current_price=signal.latest_price,
                strategy=cfg.mode,
            )

        # --- Gate checks ---

        # 0. Ticker cooldown
        if recently_traded and ticker in recently_traded:
            return skip(f"Cooldown: traded within last {cfg.ticker_cooldown_hours}h")

        # 1. Daily dip threshold
        if signal.daily_change_pct > min_daily:
            return skip(
                f"Daily change {signal.daily_change_pct:+.2f}% above threshold {min_daily:+.2f}%"
            )

        # 2. Weekly dip threshold (only for modes with require_both_timeframes)
        if (
            cfg.require_both_timeframes
            and cfg.min_weekly_dip_pct is not None
            and signal.weekly_change_pct > cfg.min_weekly_dip_pct
        ):
            return skip(
                f"Weekly change {signal.weekly_change_pct:+.2f}% "
                f"above threshold {cfg.min_weekly_dip_pct:+.2f}%"
            )

        # 3. RSI gate — don't buy if momentum isn't oversold yet
        if signal.rsi > cfg.rsi_max_buy:
            return skip(f"RSI {signal.rsi:.1f} above max {cfg.rsi_max_buy}")

        # 4. Cash reserve check
        if available_cash <= cfg.min_cash_reserve_gbp:
            return skip(
                f"Insufficient cash "
                f"(£{available_cash:.2f} ≤ reserve £{cfg.min_cash_reserve_gbp:.2f})"
            )

        # --- Size the trade ---

        # Base: % of available cash
        cash_budget = available_cash * max_cash_pct

        # If we hold a position, also cap by max_position_increase_pct
        if position is not None:
            position_value = float(position.market_value)
            max_from_position = position_value * (cfg.max_position_increase_pct / 100)
            trade_value = min(cash_budget, max_from_position)
        else:
            # New position — use cash budget directly, but cap at max portfolio weight
            max_from_weight = total_portfolio_value * (cfg.max_portfolio_weight_pct / 100)
            trade_value = min(cash_budget, max_from_weight)

        # Ensure we don't exceed available cash (less reserve)
        trade_value = min(trade_value, available_cash - cfg.min_cash_reserve_gbp)

        # Minimum trade size check
        if trade_value < cfg.min_trade_gbp:
            return skip(f"Trade size £{trade_value:.2f} below minimum £{cfg.min_trade_gbp:.2f}")

        if fx_rate is None:
            return skip(f"No FX rate for quote currency {signal.currency or 'unknown'}")

        # --- Compute limit price if applicable (in the quote currency) ---
        limit_price: float | None = None
        if cfg.order_type == "limit":
            limit_price = _round_down(
                signal.latest_price * (1 - cfg.limit_discount_pct / 100), LIMIT_PRICE_DECIMALS
            )
            if limit_price <= 0:
                return skip(f"Limit price {limit_price} too small to place")

        # --- Convert the account-currency budget into a share count ---
        order_price = limit_price if limit_price is not None else signal.latest_price
        quantity = _round_down(trade_value * fx_rate / order_price, QUANTITY_DECIMALS)
        if quantity <= 0:
            return skip(f"Trade size £{trade_value:.2f} buys less than one share fraction")

        reason = (
            f"Daily: {signal.daily_change_pct:+.2f}%, "
            f"Weekly: {signal.weekly_change_pct:+.2f}%, "
            f"RSI: {signal.rsi:.1f}"
        )

        return TradeDecision(
            ticker=ticker,
            should_trade=True,
            trade_value_gbp=round(trade_value, 2),
            reason=reason,
            daily_change_pct=signal.daily_change_pct,
            weekly_change_pct=signal.weekly_change_pct,
            rsi=signal.rsi,
            current_price=signal.latest_price,
            limit_price=limit_price,
            strategy=cfg.mode,
            quantity=quantity,
            currency=signal.currency,
        )

    def rank_decisions(self, decisions: list[TradeDecision]) -> list[TradeDecision]:
        """
        Rank trade decisions by downtrend strength — biggest dip first.
        Only returns decisions where should_trade is True.
        """
        tradeable = [d for d in decisions if d.should_trade]
        # Sort by combined daily+weekly move (most negative first)
        tradeable.sort(
            key=lambda d: (d.daily_change_pct * 0.4) + (d.weekly_change_pct * 0.6)
        )
        return tradeable[: self.config.max_trades_per_run]


class TradeExecutor:
    """Executes ranked decisions against the Trading212 API."""

    def __init__(self, client: Trading212Client, dry_run: bool = False) -> None:
        self.client = client
        self.dry_run = dry_run

    async def execute(self, decision: TradeDecision) -> bool:
        if self.dry_run:
            logger.info("[DRY RUN] Would execute: %s", decision)
            return True

        t212_ticker = decision.t212_ticker or decision.ticker

        try:
            # Limit price is only set for decisions from limit-order strategies
            if decision.limit_price is not None:
                await self.client.place_limit_order(
                    ticker=t212_ticker,
                    quantity=decision.quantity,
                    limit_price=decision.limit_price,
                    time_validity=TimeValidity.DAY,
                )
            else:
                await self.client.place_market_order(
                    ticker=t212_ticker,
                    quantity=decision.quantity,
                )
            logger.info("Executed: %s", decision)
            return True
        except Exception as e:
            logger.error("Failed to execute %s: %s", decision.ticker, e)
            return False
