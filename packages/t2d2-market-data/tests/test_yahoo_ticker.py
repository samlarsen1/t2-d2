"""Tests for mapping configured symbols to Yahoo Finance tickers."""
from __future__ import annotations

import pytest
from t2d2_market_data.providers.yahoo import to_yahoo_ticker


@pytest.mark.parametrize(
    ("symbol", "market", "expected"),
    [
        ("ETN", "us", "ETN"),
        ("RR", "uk", "RR.L"),
        ("ADYEN", "europe", "ADYEN.AS"),  # Amsterdam, not the Xetra default
        ("SIE", "europe", "SIE.DE"),
    ],
)
def test_to_yahoo_ticker(symbol: str, market: str, expected: str) -> None:
    assert to_yahoo_ticker(symbol, market) == expected
