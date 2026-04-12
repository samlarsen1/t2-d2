"""
T2-D2 Algorithm Engine.

Evaluates trend signals against strategy config to produce TradeDecisions,
then executes orders via the Trading212 client.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from t2d2_client import Position, Trading212Client
from t2d2_client.models import TimeValidity
from t2d2_market_data.analysis import TrendSignal

from .strategies.base import StrategyConfig, TradeDecision

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    session: str
    strategy_mode: str
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
            f"=== T2-D2 Run: {self.session} [{self.strategy_mode}] ===",
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


def load_strategy_config(config_dir: Path, mode_override: str | None = None) -> StrategyConfig:
    strategy_path = config_dir / "strategy.yaml"
    with open(strategy_path) as f:
        raw = yaml.safe_load(f)

    active_mode = mode_override or raw["active_mode"]
    mode_cfg = raw["modes"][active_mode]
    global_cfg = raw["global_limits"]
    analysis_cfg = raw["analysis"]

    return StrategyConfig(
        mode=active_mode,
        min_daily_dip_pct=mode_cfg["min_daily_dip_pct"],
        min_weekly_dip_pct=mode_cfg["min_weekly_dip_pct"],
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
        require_both_timeframes=global_cfg["require_both_timeframes"],
        rsi_max_buy=analysis_cfg["rsi_max_buy"],
        daily_lookback_days=analysis_cfg["daily_lookback_days"],
        weekly_lookback_days=analysis_cfg["weekly_lookback_days"],
    )


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
        ticker_override: dict[str, Any] | None = None,
        recently_traded: set[str] | None = None,
    ) -> TradeDecision:
        """
        Evaluate a single ticker's signal and decide whether to trade.

        Args:
            signal: Trend data for the ticker.
            position: Current held position (None if not held).
            available_cash: Free ISA cash in account currency.
            total_portfolio_value: Total invested + cash.
            ticker_override: Per-ticker strategy overrides from stocks.yaml.
        """
        cfg = self.config
        ticker = signal.ticker

        # Apply per-ticker mode override if present
        if ticker_override and "mode" in ticker_override:
            # Quick override: just adjust thresholds for this ticker
            override_mode = ticker_override["mode"]
            if override_mode == "mild":
                min_daily = -3.0
                max_cash_pct = ticker_override.get("max_cash_pct", cfg.max_cash_deploy_pct / 100)
            elif override_mode == "aggressive":
                min_daily = -1.0
                max_cash_pct = ticker_override.get("max_cash_pct", cfg.max_cash_deploy_pct / 100)
            else:
                min_daily = cfg.min_daily_dip_pct
                max_cash_pct = cfg.max_cash_deploy_pct / 100
        else:
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

        # 2. Weekly dip threshold (optional gating)
        if cfg.require_both_timeframes and signal.weekly_change_pct > cfg.min_weekly_dip_pct:
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

        # --- Compute limit price if applicable ---
        limit_price: float | None = None
        if cfg.order_type == "limit":
            limit_price = signal.latest_price * (1 - cfg.limit_discount_pct / 100)

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

    def __init__(self, client: Trading212Client, config: StrategyConfig, dry_run: bool = False) -> None:  # noqa: E501
        self.client = client
        self.config = config
        self.dry_run = dry_run

    async def execute(self, decision: TradeDecision) -> bool:
        if self.dry_run:
            logger.info("[DRY RUN] Would execute: %s", decision)
            return True

        t212_ticker = decision.t212_ticker or decision.ticker

        try:
            if self.config.order_type == "limit" and decision.limit_price:
                # Estimate quantity from value
                quantity = decision.trade_value_gbp / decision.current_price
                await self.client.place_limit_order(
                    ticker=t212_ticker,
                    quantity=round(quantity, 4),
                    limit_price=decision.limit_price,
                    time_validity=TimeValidity.DAY,
                )
            else:
                quantity = decision.trade_value_gbp / decision.current_price
                await self.client.place_market_order(
                    ticker=t212_ticker,
                    quantity=round(quantity, 4),
                )
            logger.info("Executed: %s", decision)
            return True
        except Exception as e:
            logger.error("Failed to execute %s: %s", decision.ticker, e)
            return False
