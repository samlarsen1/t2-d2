"""Tests for TrendAnalyser."""
from __future__ import annotations

import pandas as pd
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
