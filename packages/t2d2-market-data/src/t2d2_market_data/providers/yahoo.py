"""
Yahoo Finance market data provider via yfinance.

Handles ticker symbol mapping between Trading212 codes and Yahoo Finance codes
(e.g. LSE tickers need a `.L` suffix, Xetra tickers need `.DE`, etc.)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Trading212 ticker → Yahoo Finance ticker suffix mapping by market
MARKET_SUFFIX: dict[str, str] = {
    "uk": ".L",
    "europe": ".DE",  # Default European to Xetra; override per-ticker as needed
    "us": "",
}

# Per-ticker Yahoo Finance symbol overrides (Trading212 code → Yahoo code)
TICKER_OVERRIDES: dict[str, str] = {
    "BRK_B": "BRK-B",
    "SHEL": "SHEL.L",
    "BATS": "BATS.L",
    "LLOY": "LLOY.L",
    "AZN": "AZN.L",
    "HSBA": "HSBA.L",
    "VOD": "VOD.L",
    "NG.": "NG.L",     # National Grid — avoid double-dot from suffix append
    "MC": "MC.PA",     # LVMH is on Euronext Paris
    "SIE": "SIE.DE",
    "SAP": "SAP.DE",
    "ASML": "ASML.AS",  # Euronext Amsterdam
    "ALV": "ALV.DE",
    "VWRP": "VWRP.L",
}


def to_yahoo_ticker(t212_ticker: str, market: str = "us") -> str:
    if t212_ticker in TICKER_OVERRIDES:
        return TICKER_OVERRIDES[t212_ticker]
    suffix = MARKET_SUFFIX.get(market, "")
    return f"{t212_ticker}{suffix}"


class OHLCVData:
    def __init__(self, df: pd.DataFrame, ticker: str) -> None:
        self.ticker = ticker
        self.df = df  # DatetimeIndex, columns: Open High Low Close Volume

    @property
    def latest_close(self) -> float:
        return float(self.df["Close"].iloc[-1])

    @property
    def previous_close(self) -> float:
        return float(self.df["Close"].iloc[-2]) if len(self.df) >= 2 else self.latest_close

    def daily_change_pct(self) -> float:
        """% change from previous close to latest close."""
        prev = self.previous_close
        if prev == 0:
            return 0.0
        return ((self.latest_close - prev) / prev) * 100

    def period_change_pct(self, days: int) -> float:
        """% change over last N trading days."""
        if len(self.df) < days + 1:
            days = len(self.df) - 1
        start_price = float(self.df["Close"].iloc[-(days + 1)])
        if start_price == 0:
            return 0.0
        return ((self.latest_close - start_price) / start_price) * 100


class YahooFinanceProvider:
    """Fetches OHLCV data from Yahoo Finance."""

    def __init__(self, cache_ttl_seconds: int = 300) -> None:
        self._cache: dict[str, tuple[float, OHLCVData]] = {}
        self._cache_ttl = cache_ttl_seconds

    def _cache_key(self, ticker: str, period_days: int) -> str:
        return f"{ticker}:{period_days}"

    def _is_cached(self, key: str) -> bool:
        import time
        if key not in self._cache:
            return False
        ts, _ = self._cache[key]
        return (time.time() - ts) < self._cache_ttl

    def fetch(self, yahoo_ticker: str, period_days: int = 30) -> OHLCVData:
        """Synchronous fetch — wraps yfinance download."""
        key = self._cache_key(yahoo_ticker, period_days)
        if self._is_cached(key):
            return self._cache[key][1]

        import time
        end = date.today()
        start = end - timedelta(days=period_days + 10)  # Buffer for weekends/holidays

        try:
            df = yf.download(
                yahoo_ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            logger.error("Yahoo Finance fetch failed for %s: %s", yahoo_ticker, e)
            raise

        if df.empty:
            raise ValueError(f"No data returned for {yahoo_ticker}")

        # yfinance may return MultiIndex columns when fetching single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        data = OHLCVData(df.tail(period_days), yahoo_ticker)
        self._cache[key] = (time.time(), data)
        logger.debug("Fetched %d rows for %s", len(df), yahoo_ticker)
        return data

    async def fetch_async(self, yahoo_ticker: str, period_days: int = 30) -> OHLCVData:
        """Async wrapper — runs synchronous yfinance in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch, yahoo_ticker, period_days)

    async def fetch_multiple(
        self,
        tickers: list[tuple[str, str]],  # [(t212_ticker, market), ...]
        period_days: int = 30,
    ) -> dict[str, OHLCVData]:
        """Fetch multiple tickers concurrently."""
        tasks = {
            t212: self.fetch_async(to_yahoo_ticker(t212, market), period_days)
            for t212, market in tickers
        }
        results: dict[str, OHLCVData] = {}
        for t212, coro in tasks.items():
            try:
                results[t212] = await coro
            except Exception as e:
                logger.warning("Failed to fetch data for %s: %s", t212, e)
        return results
