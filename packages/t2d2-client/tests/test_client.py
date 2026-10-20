"""Tests for Trading212Client against mocked Trading212 API responses."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from t2d2_client import Trading212Client
from t2d2_client.client import Trading212Error

ACCOUNT_SUMMARY = {
    "id": 12345678,
    "currency": "GBP",
    "cash": {"availableToTrade": 1523.45, "inPies": 0, "reservedForOrders": 100.0},
    "investments": {
        "currentValue": 4876.21,
        "totalCost": 4500.0,
        "realizedProfitLoss": 120.5,
        "unrealizedProfitLoss": 376.21,
    },
    "totalValue": 6499.66,
}

AAPL_POSITION = {
    "instrument": {
        "ticker": "AAPL_US_EQ",
        "name": "Apple",
        "isin": "US0378331005",
        "currency": "USD",
    },
    "quantity": 2.5,
    "quantityAvailableForTrading": 2.5,
    "quantityInPies": 0,
    "averagePricePaid": 180.0,
    "currentPrice": 200.0,
    "createdAt": "2026-09-01T14:30:00Z",
    "walletImpact": {
        "currency": "GBP",
        "currentValue": 395.0,
        "totalCost": 355.0,
        "unrealizedProfitLoss": 40.0,
        "fxImpact": -2.1,
    },
}


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> Trading212Client:
    client = Trading212Client(api_key="key", api_secret="secret")
    client._client = httpx.AsyncClient(
        base_url="https://live.trading212.com", transport=httpx.MockTransport(handler)
    )
    return client


async def test_get_account_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/equity/account/summary"
        return httpx.Response(200, json=ACCOUNT_SUMMARY)

    async with make_client(handler) as client:
        summary = await client.get_account_summary()

    assert summary.currency == "GBP"
    assert summary.cash.available_to_trade == Decimal("1523.45")
    assert summary.investments.current_value == Decimal("4876.21")
    assert summary.total_value == Decimal("6499.66")


async def test_get_positions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/equity/positions"
        assert "ticker" not in request.url.params
        return httpx.Response(200, json=[AAPL_POSITION])

    async with make_client(handler) as client:
        positions = await client.get_positions()

    assert len(positions) == 1
    position = positions[0]
    assert position.ticker == "AAPL_US_EQ"
    assert position.average_price == Decimal("180.0")
    # Market value comes from walletImpact, i.e. in account currency (GBP), not USD
    assert position.market_value == Decimal("395.0")
    assert position.pnl_pct == pytest.approx(Decimal("11.1111"), abs=Decimal("0.001"))


async def test_get_position_filters_by_ticker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/equity/positions"
        assert request.url.params["ticker"] == "AAPL_US_EQ"
        return httpx.Response(200, json=[AAPL_POSITION])

    async with make_client(handler) as client:
        position = await client.get_position("AAPL_US_EQ")

    assert position is not None
    assert position.ticker == "AAPL_US_EQ"


async def test_get_position_not_held_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with make_client(handler) as client:
        assert await client.get_position("MSFT_US_EQ") is None


async def test_missing_scope_raises_trading212_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "Scope( account ) missing for API key"})

    async with make_client(handler) as client:
        with pytest.raises(Trading212Error) as exc_info:
            await client.get_account_summary()

    assert exc_info.value.status_code == 403


async def test_server_error_raises_trading212_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    async with make_client(handler) as client:
        with pytest.raises(Trading212Error) as exc_info:
            await client.get_positions()

    assert exc_info.value.status_code == 503
