"""
Trading212 REST API client.

API reference: https://t212public-api-docs.redoc.ly/
Rate limits: 1 request/second for most endpoints.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import AccountCash, AccountMetadata, HistoricalOrder, Order, OrderType, Position, TimeValidity

logger = logging.getLogger(__name__)

LIVE_BASE_URL = "https://live.trading212.com"
DEMO_BASE_URL = "https://demo.trading212.com"

_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError)


class Trading212Error(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Trading212 API error {status_code}: {message}")


class Trading212Client:
    """Async Trading212 API client. Use as an async context manager."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = LIVE_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        encoded = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> "Trading212Client":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code == 429:
            raise Trading212Error(429, "Rate limited — back off and retry")
        if not response.is_success:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise Trading212Error(response.status_code, str(detail))
        if response.status_code == 204:
            return None
        return response.json()

    # -------------------------------------------------------------------------
    # Account
    # -------------------------------------------------------------------------

    async def get_account_cash(self) -> AccountCash:
        """Fetch available ISA cash balance."""
        data = await self._request("GET", "/api/v0/equity/account/cash")
        return AccountCash.model_validate(data)

    async def get_account_metadata(self) -> AccountMetadata:
        data = await self._request("GET", "/api/v0/equity/account/info")
        return AccountMetadata.model_validate(data)

    # -------------------------------------------------------------------------
    # Portfolio
    # -------------------------------------------------------------------------

    async def get_positions(self) -> list[Position]:
        """Fetch all open positions."""
        data = await self._request("GET", "/api/v0/equity/portfolio")
        return [Position.model_validate(p) for p in data]

    async def get_position(self, ticker: str) -> Position | None:
        """Fetch a specific position, returns None if not held."""
        try:
            data = await self._request("GET", f"/api/v0/equity/portfolio/{ticker}")
            return Position.model_validate(data)
        except Trading212Error as e:
            if e.status_code == 404:
                return None
            raise

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    async def place_market_order(self, ticker: str, quantity: float) -> Order:
        """Place a market buy order for a given number of shares."""
        payload = {
            "ticker": ticker,
            "quantity": quantity,
        }
        logger.info("Placing MARKET order: %s x%.4f", ticker, quantity)
        data = await self._request("POST", "/api/v0/equity/orders/market", json=payload)
        return Order.model_validate(data)

    async def place_limit_order(
        self,
        ticker: str,
        quantity: float,
        limit_price: float,
        time_validity: TimeValidity = TimeValidity.DAY,
    ) -> Order:
        """Place a limit buy order."""
        payload = {
            "ticker": ticker,
            "quantity": quantity,
            "limitPrice": limit_price,
            "timeValidity": time_validity,
        }
        logger.info(
            "Placing LIMIT order: %s x%.4f @ %.4f", ticker, quantity, limit_price
        )
        data = await self._request("POST", "/api/v0/equity/orders/limit", json=payload)
        return Order.model_validate(data)

    async def place_value_order(
        self,
        ticker: str,
        value_gbp: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
    ) -> Order:
        """
        Place an order for a specific GBP value rather than share count.
        Calculates quantity from current price internally.
        """
        position = await self.get_position(ticker)
        if position is None:
            # No existing position — fetch current price from a separate call
            # For now, raise — caller should pre-fetch price
            raise ValueError(f"No position found for {ticker}; cannot derive share price for value order")

        current_price = float(position.current_price)
        quantity = value_gbp / current_price
        quantity = round(quantity, 6)

        if order_type == OrderType.LIMIT:
            if limit_price is None:
                raise ValueError("limit_price required for LIMIT orders")
            return await self.place_limit_order(ticker, quantity, limit_price)
        return await self.place_market_order(ticker, quantity)

    async def cancel_order(self, order_id: int) -> None:
        await self._request("DELETE", f"/api/v0/equity/orders/{order_id}")
        logger.info("Cancelled order %d", order_id)

    async def get_order(self, order_id: int) -> Order:
        data = await self._request("GET", f"/api/v0/equity/orders/{order_id}")
        return Order.model_validate(data)

    async def get_all_orders(self) -> list[Order]:
        data = await self._request("GET", "/api/v0/equity/orders")
        return [Order.model_validate(o) for o in data]

    # -------------------------------------------------------------------------
    # Historical data
    # -------------------------------------------------------------------------

    async def get_order_history(
        self,
        cursor: int = 0,
        ticker: str | None = None,
        limit: int = 50,
    ) -> list[HistoricalOrder]:
        params: dict[str, Any] = {"cursor": cursor, "limit": limit}
        if ticker:
            params["ticker"] = ticker
        data = await self._request("GET", "/api/v0/equity/history/orders", params=params)
        items = data.get("items", [])
        return [HistoricalOrder.model_validate(o.get("order", o)) for o in items]
