"""Tests for per-ticker strategy validation in stocks.yaml."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from scheduler.main import (
    CONFIG_DIR,
    active_tickers,
    get_tickers_for_session,
    history_days,
    load_schedules_config,
    load_stocks_config,
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
        ("us_morning", WEDNESDAY, ["NET", "NU"]),
        ("us_afternoon", WEDNESDAY, ["NET"]),
        ("us_morning", THURSDAY, ["NET"]),
    ],
)
def test_deep_value_tickers_only_run_wednesday_morning(
    session: str, day: date, expected: list[str]
) -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    assert [t[0] for t in active_tickers(TICKERS, configs, session, day)] == expected


def test_deep_value_fetches_a_year_of_prices() -> None:
    configs = load_strategy_configs(CONFIG_DIR)

    # A year of trading days in calendar days, so ~252 rows survive weekends
    assert history_days(configs["deep_value"]) >= 365
    assert history_days(configs["mild"]) == 35
