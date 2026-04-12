from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StrategyConfig:
    """Parsed strategy configuration for a specific mode."""
    mode: str
    min_daily_dip_pct: float
    min_weekly_dip_pct: float
    max_position_increase_pct: float
    max_cash_deploy_pct: float
    order_type: str
    limit_discount_pct: float
    max_portfolio_weight_pct: float
    min_trade_gbp: float

    # Global limits (shared across all modes)
    absolute_max_cash_deploy_pct: float
    min_cash_reserve_gbp: float
    max_trades_per_run: int
    ticker_cooldown_hours: int
    require_both_timeframes: bool

    # Analysis settings
    rsi_max_buy: float
    daily_lookback_days: int
    weekly_lookback_days: int


@dataclass
class TradeDecision:
    """Output from strategy evaluation for a single ticker."""
    ticker: str
    should_trade: bool
    trade_value_gbp: float
    reason: str
    daily_change_pct: float
    weekly_change_pct: float
    rsi: float
    current_price: float
    limit_price: float | None = None

    def __str__(self) -> str:
        if self.should_trade:
            order = f"BUY £{self.trade_value_gbp:.2f}"
            if self.limit_price:
                order += f" @ limit {self.limit_price:.4f}"
            return f"{self.ticker}: {order} | {self.reason}"
        return f"{self.ticker}: SKIP | {self.reason}"
