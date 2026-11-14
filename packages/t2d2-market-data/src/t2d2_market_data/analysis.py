"""
Trend analysis — computes signals used by the algo engine to decide
whether a ticker is in a downtrend worth buying into.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import pandas as pd

from .providers.yahoo import OHLCVData

logger = logging.getLogger(__name__)


@dataclass
class TrendSignal:
    ticker: str
    latest_price: float
    daily_change_pct: float
    weekly_change_pct: float    # 5-day
    monthly_change_pct: float   # 20-day
    rsi: float
    sma_20: float
    sma_50: float
    is_below_sma20: bool
    is_below_sma50: bool
    volume_ratio: float         # Today's volume vs 20-day average
    currency: str | None = None  # Quote currency of the prices, e.g. "GBp", "USD"
    # Long-term signals; None when the price history is too short to compute them
    quarter_change_pct: float | None = None    # ~63 trading days
    half_year_change_pct: float | None = None  # ~126 trading days
    low_52w: float | None = None               # Lowest close over ~252 trading days
    pct_above_52w_low: float | None = None     # How far the latest close sits above low_52w
    # Long-term trend SMA (default 200 days) today and ``trend_slope_days`` sessions earlier;
    # None when the price history is too short to compute both
    sma_trend: float | None = None
    sma_trend_prior: float | None = None

    @property
    def is_sma_trend_rising(self) -> bool:
        """True if the long-term SMA is higher today than ``trend_slope_days`` sessions ago.

        False when either value is unknown, so a short history never passes as an uptrend.
        """
        if self.sma_trend is None or self.sma_trend_prior is None:
            return False
        return self.sma_trend > self.sma_trend_prior

    @property
    def is_downtrend(self) -> bool:
        """True if both short and medium term momentum are negative."""
        return self.daily_change_pct < 0 and self.weekly_change_pct < 0

    @property
    def trend_strength(self) -> float:
        """
        Combined downtrend score (more negative = stronger downtrend).
        Weighted average of daily and weekly moves.
        """
        return (self.daily_change_pct * 0.4) + (self.weekly_change_pct * 0.6)

    def __str__(self) -> str:
        return (
            f"{self.ticker}: {self.latest_price:.4f} {self.currency or '?'} | "
            f"1d: {self.daily_change_pct:+.2f}% | "
            f"5d: {self.weekly_change_pct:+.2f}% | "
            f"RSI: {self.rsi:.1f} | "
            f"SMA20: {'below' if self.is_below_sma20 else 'above'}"
        )


def _rsi(series: pd.Series, period: int = 14) -> float:
    """Calculate RSI for the last value in a price series."""
    delta = series.diff().dropna()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(span=period, adjust=False).mean().iloc[-1]
    avg_loss = losses.ewm(span=period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _sma(series: pd.Series, period: int) -> float:
    if len(series) < period:
        return float(series.mean())
    return float(series.tail(period).mean())


def _sma_with_prior(
    closes: pd.Series, period: int, lag: int
) -> tuple[float | None, float | None]:
    """SMA over the last ``period`` closes, and the same SMA as it stood ``lag`` closes earlier.

    Unlike ``_sma``, this never falls back to a shorter window: both values are None unless
    there are at least ``period + lag`` closes.
    """
    if len(closes) < period + lag:
        return None, None
    current = float(closes.tail(period).mean())
    prior = float(closes.iloc[-(period + lag) : len(closes) - lag].mean())
    return current, prior


def _change_over(closes: pd.Series, days: int) -> float | None:
    """% change over the last ``days`` trading days, or None without enough history."""
    if len(closes) < days + 1:
        return None
    start = float(closes.iloc[-(days + 1)])
    if start == 0:
        return None
    return (float(closes.iloc[-1]) - start) / start * 100


class TrendAnalyser:
    """Derives trading signals from OHLCV data.

    Args:
        quarter_days: Trading days in a quarter, for ``quarter_change_pct``.
        half_year_days: Trading days in half a year, for ``half_year_change_pct``.
        year_days: Trading days in a year, for the 52-week low. The low is only reported
            with a full year of history, so a recent listing never looks like it is at
            its 52-week low.
        trend_sma_days: Period of the long-term trend SMA (``sma_trend``).
        trend_slope_days: Sessions back to compare the trend SMA against
            (``sma_trend_prior``), to tell whether it is rising.
    """

    def __init__(
        self,
        quarter_days: int = 63,
        half_year_days: int = 126,
        year_days: int = 252,
        trend_sma_days: int = 200,
        trend_slope_days: int = 20,
    ) -> None:
        self.quarter_days = quarter_days
        self.half_year_days = half_year_days
        self.year_days = year_days
        self.trend_sma_days = trend_sma_days
        self.trend_slope_days = trend_slope_days

    def analyse(self, data: OHLCVData) -> TrendSignal:
        df = data.df
        closes = df["Close"].squeeze()

        if len(closes) < 2:
            raise ValueError(f"Insufficient data for {data.ticker}: {len(closes)} rows")

        latest_price = float(closes.iloc[-1])
        daily_change = data.daily_change_pct()
        weekly_change = data.period_change_pct(5)
        monthly_change = data.period_change_pct(20)

        rsi = _rsi(closes)
        sma20 = _sma(closes, 20)
        sma50 = _sma(closes, 50)

        # Volume ratio: today's volume vs 20-day average
        volumes = df["Volume"].squeeze()
        vol_avg = float(volumes.tail(20).mean()) if len(volumes) >= 20 else float(volumes.mean())
        today_vol = float(volumes.iloc[-1])
        vol_ratio = today_vol / vol_avg if vol_avg > 0 else 1.0

        low_52w: float | None = None
        pct_above_low: float | None = None
        if len(closes) >= self.year_days:
            low_52w = float(closes.tail(self.year_days).min())
            if low_52w > 0:
                pct_above_low = (latest_price - low_52w) / low_52w * 100

        sma_trend, sma_trend_prior = _sma_with_prior(
            closes, self.trend_sma_days, self.trend_slope_days
        )

        signal = TrendSignal(
            ticker=data.ticker,
            latest_price=latest_price,
            daily_change_pct=daily_change,
            weekly_change_pct=weekly_change,
            monthly_change_pct=monthly_change,
            rsi=rsi,
            sma_20=sma20,
            sma_50=sma50,
            is_below_sma20=latest_price < sma20,
            is_below_sma50=latest_price < sma50,
            volume_ratio=vol_ratio,
            currency=data.currency,
            quarter_change_pct=_change_over(closes, self.quarter_days),
            half_year_change_pct=_change_over(closes, self.half_year_days),
            low_52w=low_52w,
            pct_above_52w_low=pct_above_low,
            sma_trend=sma_trend,
            sma_trend_prior=sma_trend_prior,
        )

        logger.debug("Signal: %s", signal)
        return signal

    def analyse_many(self, data_map: dict[str, OHLCVData]) -> dict[str, TrendSignal]:
        """Analyse each entry, labelling every signal with its ``data_map`` key.

        The key (the stocks.yaml symbol, e.g. ``"CWR"``) replaces the provider's
        ticker (e.g. ``"CWR.L"``) so downstream checks such as the trade
        cooldown match on the same name.
        """
        signals: dict[str, TrendSignal] = {}
        for ticker, data in data_map.items():
            try:
                signals[ticker] = replace(self.analyse(data), ticker=ticker)
            except Exception as e:
                logger.warning("Analysis failed for %s: %s", ticker, e)
        return signals
