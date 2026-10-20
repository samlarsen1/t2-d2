"""Tests for quote-currency handling and FX rates in the Yahoo provider."""
from __future__ import annotations

from typing import Any

import pytest
import yfinance
from t2d2_market_data.providers.yahoo import YahooFinanceProvider, split_minor_unit


class _FakeTicker:
    """Stands in for yfinance.Ticker; looks up fast_info from a per-symbol table."""

    table: dict[str, dict[str, Any] | Exception] = {}

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def fast_info(self) -> dict[str, Any]:
        entry = self.table[self.symbol]
        if isinstance(entry, Exception):
            raise entry
        return entry


@pytest.fixture
def fake_yf(monkeypatch: pytest.MonkeyPatch) -> type[_FakeTicker]:
    _FakeTicker.table = {}
    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    return _FakeTicker


@pytest.mark.parametrize(
    ("currency", "expected"),
    [("GBp", ("GBP", 100)), ("GBX", ("GBP", 100)), ("USD", ("USD", 1)), ("GBP", ("GBP", 1))],
)
def test_split_minor_unit(currency: str, expected: tuple[str, int]) -> None:
    assert split_minor_unit(currency) == expected


def test_fx_rates_handle_pence_and_foreign_currencies(fake_yf: type[_FakeTicker]) -> None:
    fake_yf.table = {
        "GBPUSD=X": {"lastPrice": 1.338},
        "GBPEUR=X": {"lastPrice": 1.19},
    }
    rates = YahooFinanceProvider().fetch_fx_rates({"GBp", "GBP", "USD", "EUR"}, "GBP")
    assert rates == {"GBp": 100.0, "GBP": 1.0, "USD": 1.338, "EUR": 1.19}


def test_fx_rate_failure_omits_currency(
    fake_yf: type[_FakeTicker], caplog: pytest.LogCaptureFixture
) -> None:
    fake_yf.table = {"GBPUSD=X": TimeoutError("read timed out")}
    rates = YahooFinanceProvider().fetch_fx_rates({"USD", "GBp"}, "GBP")
    assert rates == {"GBp": 100.0}
    assert "GBPUSD=X" in caplog.text


def test_non_positive_fx_rate_ignored(fake_yf: type[_FakeTicker]) -> None:
    fake_yf.table = {"GBPUSD=X": {"lastPrice": 0.0}}
    assert YahooFinanceProvider().fetch_fx_rates({"USD"}, "GBP") == {}


def test_quote_currency_lookup(fake_yf: type[_FakeTicker]) -> None:
    fake_yf.table = {"RIO.L": {"currency": "GBp"}, "BAD": KeyError("currency")}
    provider = YahooFinanceProvider()
    assert provider._quote_currency("RIO.L") == "GBp"
    assert provider._quote_currency("BAD") is None
