"""Tests for TrendAnalyser."""
from __future__ import annotations

import pandas as pd
import pytest
from t2d2_market_data.analysis import TrendAnalyser
from t2d2_market_data.providers.yahoo import OHLCVData


def _ohlcv(yahoo_ticker: str) -> OHLCVData:
    closes = [300.0, 298.0, 295.0, 294.8, 280.0]
    df = pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1000] * 5},
        index=pd.date_range("2026-10-14", periods=5, freq="B"),
    )
    return OHLCVData(df, yahoo_ticker, currency="GBp")


def test_analyse_many_labels_signals_with_stocks_symbol() -> None:
    # Cooldowns are keyed by the stocks.yaml symbol ("CWR"), not Yahoo's "CWR.L"
    signals = TrendAnalyser().analyse_many({"CWR": _ohlcv("CWR.L"), "NG.": _ohlcv("NG.L")})

    assert signals["CWR"].ticker == "CWR"
    assert signals["NG."].ticker == "NG."
    assert signals["CWR"].currency == "GBp"
    assert signals["CWR"].latest_price == 280.0


def _history(closes: list[float]) -> OHLCVData:
    df = pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes,
         "Volume": [1000] * len(closes)},
        index=pd.date_range("2025-10-01", periods=len(closes), freq="B"),
    )
    return OHLCVData(df, "NU", currency="USD")


def test_long_term_signals_from_a_year_of_prices() -> None:
    # Flat at 100 for most of the year, then a slide to 70 over the last quarter
    closes = [100.0] * 190 + [100.0 - 30.0 * i / 62 for i in range(63)]

    signal = TrendAnalyser().analyse(_history(closes))

    assert signal.low_52w == pytest.approx(70.0)
    assert signal.pct_above_52w_low == pytest.approx(0.0)
    assert signal.quarter_change_pct == pytest.approx(-30.0)
    assert signal.half_year_change_pct == pytest.approx(-30.0)


def test_long_term_signals_none_with_short_history() -> None:
    signal = TrendAnalyser().analyse(_history([100.0, 99.0, 98.0]))

    assert signal.quarter_change_pct is None
    assert signal.half_year_change_pct is None
    assert signal.low_52w is None
    assert signal.pct_above_52w_low is None


def test_52w_low_needs_a_full_year() -> None:
    # A recent listing that has only ever fallen isn't reported as at a 52-week low
    closes = [200.0 - i for i in range(150)]

    signal = TrendAnalyser().analyse(_history(closes))

    assert signal.half_year_change_pct is not None
    assert signal.low_52w is None
