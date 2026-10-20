"""Tests for per-ticker strategy validation in stocks.yaml."""
from __future__ import annotations

from typing import Any

import pytest
from scheduler.main import (
    CONFIG_DIR,
    get_tickers_for_session,
    load_stocks_config,
    validate_stock_strategies,
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
