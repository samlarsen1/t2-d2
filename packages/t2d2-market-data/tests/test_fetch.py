"""Tests for YahooFinanceProvider.fetch date window."""
from __future__ import annotations

from datetime import date, timedelta
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
