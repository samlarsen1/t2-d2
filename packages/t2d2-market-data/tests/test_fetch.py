"""Tests for YahooFinanceProvider.fetch date window."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yfinance


def test_fetch_includes_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from t2d2_market_data.providers.yahoo import YahooFinanceProvider

    calls: list[dict[str, Any]] = []
    today = date.today()
    bars = pd.DataFrame(
        {"Open": [96.0, 97.0], "High": [97.0, 99.0], "Low": [95.0, 96.5],
         "Close": [96.52, 98.27], "Volume": [1000, 1200]},
        index=pd.to_datetime([today - timedelta(days=1), today]),
    )

    def fake_download(ticker: str, **kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        return bars

    monkeypatch.setattr(yfinance, "download", fake_download)
    monkeypatch.setattr(YahooFinanceProvider, "_quote_currency", lambda self, t: "USD")

    data = YahooFinanceProvider().fetch("HOOD", period_days=30)

    # `end` is exclusive in yfinance, so it must be tomorrow for today's bar to be returned
    assert calls[0]["end"] == (today + timedelta(days=1)).isoformat()
    assert data.latest_close == 98.27
    assert round(data.daily_change_pct(), 2) == 1.81


# --- Disk price cache ---------------------------------------------------------


class FakeYahoo:
    """Serves bars from a fixed history, recording each requested window."""

    def __init__(self, closes: pd.Series) -> None:
        self.closes = closes
        self.calls: list[tuple[date, date]] = []
        self.error: Exception | None = None

    def download(self, ticker: str, **kwargs: Any) -> pd.DataFrame:
        if self.error:
            raise self.error
        start, end = date.fromisoformat(kwargs["start"]), date.fromisoformat(kwargs["end"])
        self.calls.append((start, end))
        window = self.closes[
            (self.closes.index >= pd.Timestamp(start)) & (self.closes.index < pd.Timestamp(end))
        ]
        return pd.DataFrame(
            {"Open": window, "High": window, "Low": window, "Close": window,
             "Volume": [1000] * len(window)},
            index=window.index,
        )


def _history_until_today(days: int = 120, factor: float = 1.0) -> pd.Series:
    # Daily (not business-day) bars, so a bar for today exists whatever day the tests run
    index = pd.date_range(end=pd.Timestamp(date.today()), periods=days, freq="D")
    return pd.Series([factor * (100.0 + i) for i in range(days)], index=index)


@pytest.fixture
def yahoo(monkeypatch: pytest.MonkeyPatch) -> FakeYahoo:
    from t2d2_market_data.providers.yahoo import YahooFinanceProvider

    fake = FakeYahoo(_history_until_today())
    monkeypatch.setattr(yfinance, "download", fake.download)
    monkeypatch.setattr(YahooFinanceProvider, "_quote_currency", lambda self, t: "USD")
    return fake


def _provider(cache_dir: Path) -> Any:
    from t2d2_market_data import PriceCache, YahooFinanceProvider

    return YahooFinanceProvider(cache_ttl_seconds=0, price_cache=PriceCache(cache_dir))


def test_first_fetch_downloads_full_window_and_caches_completed_bars(
    yahoo: FakeYahoo, tmp_path: Path
) -> None:
    data = _provider(tmp_path).fetch("AAPL", period_days=60)

    today = date.today()
    assert yahoo.calls == [(today - timedelta(days=70), today + timedelta(days=1))]
    assert data.latest_close == float(yahoo.closes.iloc[-1])
    # Today's bar may still change intraday, so it is never cached
    assert not (tmp_path / today.isoformat()).exists()
    assert (tmp_path / yahoo.closes.index[-2].date().isoformat() / "AAPL.csv").is_file()


def test_second_fetch_only_downloads_the_latest_bars(yahoo: FakeYahoo, tmp_path: Path) -> None:
    first = _provider(tmp_path).fetch("AAPL", period_days=60)
    yahoo.calls.clear()

    second = _provider(tmp_path).fetch("AAPL", period_days=60)

    (start, end), = yahoo.calls
    assert end == date.today() + timedelta(days=1)
    # Re-downloads the last 5 cached bars (to spot re-adjusted prices) plus today
    assert start == yahoo.closes.index[-6].date()
    assert list(second.df.index.date) == list(first.df.index.date)
    assert list(second.df["Close"]) == list(first.df["Close"])


def test_split_invalidates_the_cache_and_refetches_everything(
    yahoo: FakeYahoo, tmp_path: Path
) -> None:
    _provider(tmp_path).fetch("AAPL", period_days=60)
    # A 4:1 split: Yahoo now reports every past close at a quarter of the cached value
    yahoo.closes = _history_until_today(factor=0.25)
    yahoo.calls.clear()

    data = _provider(tmp_path).fetch("AAPL", period_days=60)

    today = date.today()
    assert yahoo.calls[-1] == (today - timedelta(days=70), today + timedelta(days=1))
    assert list(data.df["Close"]) == list(yahoo.closes.tail(len(data.df)))
    # The cache now holds the adjusted prices
    cached = pd.read_csv(
        tmp_path / yahoo.closes.index[-2].date().isoformat() / "AAPL.csv", index_col=0
    )
    assert float(cached["Close"].iloc[0]) == pytest.approx(float(yahoo.closes.iloc[-2]))


def test_cache_too_short_for_a_longer_window_downloads_full_history(
    yahoo: FakeYahoo, tmp_path: Path
) -> None:
    _provider(tmp_path).fetch("AAPL", period_days=20)
    yahoo.calls.clear()

    _provider(tmp_path).fetch("AAPL", period_days=100)

    today = date.today()
    assert yahoo.calls == [(today - timedelta(days=110), today + timedelta(days=1))]


@pytest.mark.parametrize(
    "error", [TimeoutError("read timed out"), ConnectionError("HTTP 503"),
              RuntimeError("YFRateLimitError: Too Many Requests")],
)
def test_download_errors_propagate_and_keep_the_cache(
    yahoo: FakeYahoo, tmp_path: Path, error: Exception
) -> None:
    _provider(tmp_path).fetch("AAPL", period_days=60)
    files_before = sorted(tmp_path.rglob("*.csv"))
    yahoo.error = error

    with pytest.raises(type(error)):
        _provider(tmp_path).fetch("AAPL", period_days=60)

    assert sorted(tmp_path.rglob("*.csv")) == files_before


def test_empty_download_raises_without_writing_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from t2d2_market_data.providers.yahoo import YahooFinanceProvider

    monkeypatch.setattr(yfinance, "download", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(YahooFinanceProvider, "_quote_currency", lambda self, t: "USD")

    with pytest.raises(ValueError, match="No data returned"):
        _provider(tmp_path).fetch("DELISTED", period_days=30)
    assert not list(tmp_path.rglob("*.csv"))
