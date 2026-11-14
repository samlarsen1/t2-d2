"""Tests for the date-partitioned PriceCache."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from t2d2_market_data.cache import PriceCache


def _bars(start: str, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes,
         "Volume": [1000] * len(closes)},
        index=pd.date_range(start, periods=len(closes), freq="B"),
    )


def test_save_writes_one_file_per_date_partition(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path)

    assert cache.save("NG.L", _bars("2026-11-09", [100.0, 101.0, 102.0])) == 3

    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-09", "2026-11-10", "2026-11-11"]
    assert (tmp_path / "2026-11-10" / "NG.L.csv").is_file()


def test_load_round_trips_within_the_date_range(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path)
    cache.save("AAPL", _bars("2026-11-09", [100.0, 101.0, 102.0, 103.0]))
    cache.save("MSFT", _bars("2026-11-09", [400.0, 401.0]))

    loaded = cache.load("AAPL", date(2026, 11, 10), date(2026, 11, 12))

    assert list(loaded["Close"]) == [101.0, 102.0]
    assert list(loaded.index.date) == [date(2026, 11, 10), date(2026, 11, 11)]
    assert list(loaded.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_load_is_empty_without_a_cache(tmp_path: Path) -> None:
    loaded = PriceCache(tmp_path / "missing").load("AAPL", date(2026, 1, 1), date(2026, 12, 1))

    assert loaded.empty


def test_save_replaces_a_cached_bar(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path)
    cache.save("AAPL", _bars("2026-11-09", [100.0]))
    cache.save("AAPL", _bars("2026-11-09", [99.0]))

    loaded = cache.load("AAPL", date(2026, 11, 9), date(2026, 11, 10))

    assert list(loaded["Close"]) == [99.0]
    assert not list((tmp_path / "2026-11-09").glob("*.tmp"))


def test_delete_ticker_only_removes_that_ticker(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path)
    cache.save("AAPL", _bars("2026-11-09", [100.0, 101.0]))
    cache.save("MSFT", _bars("2026-11-09", [400.0, 401.0]))

    assert cache.delete_ticker("AAPL") == 2

    assert cache.load("AAPL", date(2026, 1, 1), date(2027, 1, 1)).empty
    assert len(cache.load("MSFT", date(2026, 1, 1), date(2027, 1, 1))) == 2


def test_prune_removes_only_old_date_partitions(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path)
    cache.save("AAPL", _bars("2025-01-02", [90.0]))
    cache.save("AAPL", _bars("2026-11-09", [100.0]))
    (tmp_path / "notes").mkdir()
    (tmp_path / "1999-01-01.txt").write_text("not a partition")

    removed = cache.prune(keep_days=300, today=date(2026, 11, 14))

    assert removed == [tmp_path / "2025-01-02"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["1999-01-01.txt", "2026-11-09", "notes"]


def test_prune_keeps_the_partition_exactly_at_the_limit(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path)
    cache.save("AAPL", _bars("2026-11-04", [100.0]))

    assert cache.prune(keep_days=10, today=date(2026, 11, 14)) == []


def test_prune_without_a_cache_folder(tmp_path: Path) -> None:
    assert PriceCache(tmp_path / "missing").prune(keep_days=1, today=date(2026, 11, 14)) == []


@pytest.mark.parametrize("ticker", ["../etc", "..", "a/b", "", ".hidden", "A..B"])
def test_unsafe_tickers_are_rejected(tmp_path: Path, ticker: str) -> None:
    with pytest.raises(ValueError, match="Unsafe ticker"):
        PriceCache(tmp_path).save(ticker, _bars("2026-11-09", [1.0]))
