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


class TrendAnalyser:
    """Derives trading signals from OHLCV data."""

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
