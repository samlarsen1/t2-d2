"""Tests for Trading212 instrument page links."""
from __future__ import annotations

import pytest
from t2d2_algo.engine import RunResult
from t2d2_algo.links import instrument_url
from t2d2_algo.strategies.base import TradeDecision


@pytest.mark.parametrize(
    ("t212_ticker", "expected"),
    [
        ("TSLA_US_EQ", "https://www.trading212.com/trading-instruments/invest/TSLA.US"),
        ("RIOl_EQ", "https://www.trading212.com/trading-instruments/invest/RIO.UK"),
        ("NGl_EQ", "https://www.trading212.com/trading-instruments/invest/NG.UK"),
        ("ASMLa_EQ", "https://www.trading212.com/trading-instruments/invest/ASML.NL"),
        ("SAPd_EQ", "https://www.trading212.com/trading-instruments/invest/SAP.DE"),
    ],
)
def test_instrument_url_known_exchanges(t212_ticker: str, expected: str) -> None:
    assert instrument_url(t212_ticker) == expected


@pytest.mark.parametrize("t212_ticker", ["TSLA", "RIOx_EQ", "EURUSD", ""])
def test_instrument_url_unrecognised_code(t212_ticker: str) -> None:
    assert instrument_url(t212_ticker) is None


def _trade(ticker: str, t212_ticker: str | None) -> TradeDecision:
    return TradeDecision(
        ticker=ticker,
        should_trade=True,
        trade_value_gbp=50.0,
        reason="dip",
        daily_change_pct=-3.0,
        weekly_change_pct=-5.0,
        rsi=30.0,
        current_price=100.0,
        t212_ticker=t212_ticker,
    )


def test_summary_lists_instrument_url_under_each_trade() -> None:
    result = RunResult(session="us_morning", available_cash_gbp=1000.0)
    result.executed_trades = [_trade("TSLA", "TSLA_US_EQ"), _trade("ODD", None)]

    lines = result.summary().splitlines()

    tsla = next(i for i, line in enumerate(lines) if line.startswith("  TSLA"))
    assert lines[tsla + 1] == "    https://www.trading212.com/trading-instruments/invest/TSLA.US"
    # No link line for a code whose exchange is unknown
    assert lines[-1].startswith("  ODD")
