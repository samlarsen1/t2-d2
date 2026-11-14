"""Tests for per-ticker strategy validation in stocks.yaml."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from scheduler.main import (
    CONFIG_DIR,
    DEFAULT_DATA_DIR,
    active_tickers,
    cache_retention_days,
    get_tickers_for_session,
    history_days,
    load_schedules_config,
    load_stocks_config,
    price_cache_dir,
    validate_session_strategies,
    validate_stock_strategies,
    validate_strategy_sessions,
)
from t2d2_algo import load_strategy_configs

STRATEGIES = {"mild", "moderate", "aggressive"}


def make_stocks(*tickers: dict[str, Any]) -> dict[str, Any]:
    return {"markets": {"us": {"currency": "USD", "tickers": list(tickers)}}}


def test_valid_strategies_pass() -> None:
    stocks = make_stocks(
        {"symbol": "NET", "t212_ticker": "NET_US_EQ", "strategy": "mild"},
        {"symbol": "AMD", "t212_ticker": "AMD_US_EQ", "strategy": "moderate"},
    )
    validate_stock_strategies(stocks, STRATEGIES)


def test_missing_strategy_rejected() -> None:
    stocks = make_stocks({"symbol": "NET", "t212_ticker": "NET_US_EQ"})
    with pytest.raises(ValueError, match="us/NET: missing 'strategy'"):
        validate_stock_strategies(stocks, STRATEGIES)


def test_unknown_strategy_rejected() -> None:
    stocks = make_stocks({"symbol": "NET", "strategy": "yolo"})
    with pytest.raises(ValueError, match="us/NET: unknown strategy 'yolo'"):
        validate_stock_strategies(stocks, STRATEGIES)


def test_all_problems_reported_together() -> None:
    stocks = make_stocks({"symbol": "NET"}, {"symbol": "AMD", "strategy": "yolo"})
    with pytest.raises(ValueError) as exc_info:
        validate_stock_strategies(stocks, STRATEGIES)
    assert "us/NET" in str(exc_info.value)
    assert "us/AMD" in str(exc_info.value)


def test_tickers_include_strategy() -> None:
    stocks = make_stocks({"symbol": "RKLB", "t212_ticker": "VACQ_US_EQ", "strategy": "mild"})
    assert get_tickers_for_session(stocks, ["us"]) == [("RKLB", "VACQ_US_EQ", "us", "mild")]


def test_repo_stocks_config_is_valid() -> None:
    """Guard against committing a stocks.yaml ticker without a valid strategy."""
    validate_stock_strategies(load_stocks_config(), set(load_strategy_configs(CONFIG_DIR)))


def test_repo_strategy_sessions_are_valid() -> None:
    validate_strategy_sessions(
        load_strategy_configs(CONFIG_DIR), set(load_schedules_config()["sessions"])
    )


def test_unknown_trade_session_rejected() -> None:
    configs = load_strategy_configs(CONFIG_DIR)
    configs["deep_value"].trade_sessions = ["us_lunch"]

    with pytest.raises(ValueError, match="deep_value: unknown session 'us_lunch'"):
        validate_strategy_sessions(configs, {"us_morning"})


WEDNESDAY = date(2026, 11, 18)
THURSDAY = date(2026, 11, 19)
TICKERS = [("NET", "NET_US_EQ", "us", "mild"), ("NU", "NU_US_EQ", "us", "deep_value")]


@pytest.mark.parametrize(
    ("session", "day", "expected"),
    [
        ("deep_value_midweek", WEDNESDAY, ["NU"]),
        ("deep_value_midweek", THURSDAY, []),  # e.g. a manual run on the wrong day
        ("us_morning", WEDNESDAY, ["NET"]),
        ("us_afternoon", WEDNESDAY, ["NET"]),
    ],
)
def test_deep_value_tickers_only_run_in_midweek_session(
    session: str, day: date, expected: list[str]
) -> None:
    configs = load_strategy_configs(CONFIG_DIR)
    session_strategies = load_schedules_config()["sessions"][session].get("strategies")

    active = active_tickers(TICKERS, configs, session, day, session_strategies=session_strategies)

    assert [t[0] for t in active] == expected


def test_session_strategies_filter_drops_other_strategies() -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    active = active_tickers(TICKERS, configs, "us_morning", WEDNESDAY, session_strategies=["mild"])

    assert [t[0] for t in active] == ["NET"]


def test_repo_session_strategies_are_valid() -> None:
    validate_session_strategies(
        load_schedules_config()["sessions"], set(load_strategy_configs(CONFIG_DIR))
    )


def test_unknown_session_strategy_rejected() -> None:
    sessions = {"deep_value_midweek": {"markets": ["us"], "strategies": ["deep_valu"]}}

    with pytest.raises(ValueError, match="deep_value_midweek: unknown strategy 'deep_valu'"):
        validate_session_strategies(sessions, {"deep_value", "mild"})


def test_midweek_session_covers_eu_and_us_on_wednesday() -> None:
    session = load_schedules_config()["sessions"]["deep_value_midweek"]

    assert session["schedule"].startswith("Wed ")
    assert {"uk", "europe", "us"} <= set(session["markets"])
    assert session["strategies"] == ["deep_value"]


def test_deep_value_fetches_a_year_of_prices() -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    # A year of trading days in calendar days, so ~252 rows survive weekends
    assert history_days(configs["deep_value"]) >= 365


def test_every_mode_fetches_enough_prices_for_the_sma200_slope() -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    for mode, config in configs.items():
        if not config.require_rising_trend_sma:
            continue
        days = history_days(config)
        # Weekdays in the fetched window, less up to ~10 exchange holidays a year,
        # must still leave 200 + 20 closes (the provider adds 10 calendar days of slack)
        weekdays = (days + 10) * 5 // 7
        assert weekdays - 10 >= config.trend_history_days, mode
    assert history_days(configs["mild"]) == 331


def test_deep_value_history_is_unchanged_by_the_sma_gate() -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    # Exempt from the gate, so its window is still the one-year lookback
    assert history_days(configs["deep_value"]) == 380


def test_cache_retention_covers_the_longest_fetch_window() -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    longest = max(history_days(c) for c in configs.values())
    # The provider fetches 10 calendar days on top of history_days
    assert cache_retention_days(configs) >= longest + 10
    assert cache_retention_days(configs) == 397


def test_price_cache_dir_defaults_to_repo_data_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("T2D2_DATA_DIR", raising=False)
    assert price_cache_dir() == DEFAULT_DATA_DIR / "prices"

    monkeypatch.setenv("T2D2_DATA_DIR", "/srv/t2d2")
    assert str(price_cache_dir()) == "/srv/t2d2/prices"
