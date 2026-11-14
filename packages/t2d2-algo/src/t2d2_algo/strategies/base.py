from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Signal a mode responds to: daily/weekly dips, or a long-term (quarter, half-year, 52-week) slide
TRIGGER_DAILY_DIP = "daily_dip"
TRIGGER_LONG_TERM_DOWNTREND = "long_term_downtrend"
TRIGGERS = {TRIGGER_DAILY_DIP, TRIGGER_LONG_TERM_DOWNTREND}

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


@dataclass
class StrategyConfig:
    """Parsed strategy configuration for a specific mode."""
    mode: str
    min_daily_dip_pct: float | None  # Required for the daily_dip trigger
    min_weekly_dip_pct: float | None  # Only needed when require_both_timeframes
    max_position_increase_pct: float
    max_cash_deploy_pct: float
    order_type: str
    limit_discount_pct: float
    max_portfolio_weight_pct: float
    min_trade_gbp: float

    # Global limits (shared across all modes)
    absolute_max_cash_deploy_pct: float
    min_cash_reserve_gbp: float
    min_trade_floor_gbp: float
    limit_order_expiry_days: int
    max_trades_per_run: int
    ticker_cooldown_hours: int

    # Analysis settings
    rsi_max_buy: float
    daily_lookback_days: int
    weekly_lookback_days: int

    # Per-mode: also require the weekly dip to reach min_weekly_dip_pct
    require_both_timeframes: bool = False

    # Which signal the mode responds to (see TRIGGERS)
    trigger: str = TRIGGER_DAILY_DIP
    # long_term_downtrend thresholds: any one that is set and met triggers a buy
    max_pct_above_52w_low: float | None = None  # Within this % of the 52-week closing low
    min_quarter_change_pct: float | None = None  # Fell at least this much over a quarter
    min_half_year_change_pct: float | None = None  # Fell at least this much over half a year

    # Restrict the mode's tickers to one weekday and/or certain sessions (None = no limit)
    trade_weekday: str | None = None
    trade_sessions: list[str] | None = None

    # Trading days of history behind the long-term signals
    quarter_lookback_days: int = 63
    half_year_lookback_days: int = 126
    year_lookback_days: int = 252

    # Per-mode: only buy while the trend SMA is higher than trend_slope_days sessions earlier
    require_rising_trend_sma: bool = True
    trend_sma_days: int = 200
    trend_slope_days: int = 20

    def __post_init__(self) -> None:
        if self.trigger not in TRIGGERS:
            raise ValueError(
                f"Strategy {self.mode!r}: unknown trigger {self.trigger!r} "
                f"(valid: {', '.join(sorted(TRIGGERS))})"
            )
        if self.trigger == TRIGGER_DAILY_DIP and self.min_daily_dip_pct is None:
            raise ValueError(f"Strategy {self.mode!r}: daily_dip trigger needs min_daily_dip_pct")
        if self.require_both_timeframes and self.min_weekly_dip_pct is None:
            raise ValueError(
                f"Strategy {self.mode!r}: require_both_timeframes needs min_weekly_dip_pct"
            )
        long_term_thresholds = (
            self.max_pct_above_52w_low,
            self.min_quarter_change_pct,
            self.min_half_year_change_pct,
        )
        if self.trigger == TRIGGER_LONG_TERM_DOWNTREND and all(
            t is None for t in long_term_thresholds
        ):
            raise ValueError(
                f"Strategy {self.mode!r}: long_term_downtrend trigger needs at least one of "
                "max_pct_above_52w_low, min_quarter_change_pct, min_half_year_change_pct"
            )
        if self.trade_weekday is not None and self.trade_weekday not in WEEKDAYS:
            raise ValueError(
                f"Strategy {self.mode!r}: trade_weekday {self.trade_weekday!r} "
                f"must be one of {', '.join(WEEKDAYS)}"
            )

    @property
    def trend_history_days(self) -> int:
        """Trading days of prices needed to compare the trend SMA with its earlier value."""
        return self.trend_sma_days + self.trend_slope_days

    @property
    def needs_long_history(self) -> bool:
        """True if the mode's signals need a year of price history."""
        return self.trigger == TRIGGER_LONG_TERM_DOWNTREND

    def is_active(self, session: str, today: date) -> bool:
        """Return True if tickers on this mode should be evaluated in this session today.

        Args:
            session: Scheduler session name, e.g. ``"us_morning"``.
            today: Date of the run.
        """
        if self.trade_sessions is not None and session not in self.trade_sessions:
            return False
        if self.trade_weekday is not None and today.weekday() != WEEKDAYS.index(
            self.trade_weekday
        ):
            return False
        return True


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
    t212_ticker: str | None = None  # T212 instrument code, falls back to ticker if unset
    strategy: str | None = None  # Strategy mode that produced this decision
    quantity: float = 0.0  # Shares to buy, from trade_value_gbp converted via FX
    currency: str | None = None  # Quote currency of current/limit price
    # Ranking key across modes, most negative first; None falls back to the daily/weekly blend
    downtrend_score: float | None = None

    def __str__(self) -> str:
        label = f"{self.ticker} [{self.strategy}]" if self.strategy else self.ticker
        if self.should_trade:
            order = f"BUY £{self.trade_value_gbp:.2f} ({self.quantity} shares)"
            if self.limit_price:
                order += f" @ limit {self.limit_price:.2f} {self.currency or ''}".rstrip()
            return f"{label}: {order} | {self.reason}"
        return f"{label}: SKIP | {self.reason}"
