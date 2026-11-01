"""Tests for expiring old limit orders and blocking tickers with open orders."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace, TracebackType
from typing import Any

import pytest
from scheduler import main
from scheduler.main import (
    cancel_expired_limit_orders,
    count_filled_orders_since,
    find_expired_limit_orders,
    tickers_with_open_orders,
)
from scheduler.telegram import TelegramNotifier
from t2d2_client.client import Trading212Error
from t2d2_client.models import HistoricalOrder, Order

CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)
OLD = "2026-09-01T09:00:00Z"
RECENT = "2026-10-20T09:00:00Z"


def make_order(order_id: int = 1, **overrides: Any) -> Order:
    payload = {
        "id": order_id,
        "ticker": "AAPL_US_EQ",
        "type": "LIMIT",
        "side": "BUY",
        "status": "NEW",
        "initiatedFrom": "API",
        "quantity": 1.5,
        "limitPrice": 180.0,
        "timeInForce": "GOOD_TILL_CANCEL",
        "createdAt": OLD,
    }
    return Order.model_validate({**payload, **overrides})


class FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.cancelled: list[int] = []
        self.error = error

    async def cancel_order(self, order_id: int) -> None:
        if self.error:
            raise self.error
        self.cancelled.append(order_id)


def test_old_api_limit_buy_is_expired() -> None:
    order = make_order()
    assert find_expired_limit_orders([order], CUTOFF) == [order]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"createdAt": RECENT}, id="recent"),
        pytest.param({"initiatedFrom": "WEB"}, id="placed-in-web-app"),
        pytest.param({"initiatedFrom": "IOS"}, id="placed-in-mobile-app"),
        pytest.param({"initiatedFrom": None}, id="unknown-origin"),
        pytest.param({"side": "SELL"}, id="sell"),
        pytest.param({"type": "STOP"}, id="stop-order"),
        pytest.param({"status": "CANCELLING"}, id="already-cancelling"),
        pytest.param({"createdAt": None}, id="unknown-age"),
    ],
)
def test_other_orders_are_not_expired(overrides: dict[str, Any]) -> None:
    assert find_expired_limit_orders([make_order(**overrides)], CUTOFF) == []


async def test_cancels_only_expired_orders() -> None:
    now = datetime.now(tz=UTC)
    expired = make_order(1, createdAt=(now - timedelta(days=31)).isoformat())
    active = make_order(2, createdAt=(now - timedelta(days=29)).isoformat())
    client = FakeClient()

    cancelled = await cancel_expired_limit_orders(
        client, [expired, active], expiry_days=30, dry_run=False  # type: ignore[arg-type]
    )

    assert client.cancelled == [1]
    assert cancelled == [expired]


async def test_dry_run_cancels_nothing_but_reports_the_order() -> None:
    client = FakeClient()
    order = make_order()

    cancelled = await cancel_expired_limit_orders(
        client, [order], expiry_days=30, dry_run=True  # type: ignore[arg-type]
    )

    assert client.cancelled == []
    assert cancelled == [order]


@pytest.mark.parametrize(
    "error",
    [
        Trading212Error(404, "Order not found"),
        Trading212Error(503, "Service Unavailable"),
        TimeoutError("timed out"),
    ],
)
async def test_cancel_failure_does_not_stop_the_run(error: Exception) -> None:
    client = FakeClient(error=error)

    cancelled = await cancel_expired_limit_orders(
        client, [make_order()], expiry_days=30, dry_run=False  # type: ignore[arg-type]
    )

    assert cancelled == []


def test_open_order_blocks_ticker_past_the_cooldown() -> None:
    assert tickers_with_open_orders([make_order()], {"AAPL_US_EQ": "AAPL"}) == {"AAPL"}


def test_open_order_with_unknown_age_blocks_ticker() -> None:
    order = make_order(createdAt=None)
    assert tickers_with_open_orders([order], {"AAPL_US_EQ": "AAPL"}) == {"AAPL"}


def test_inactive_or_other_session_orders_do_not_block() -> None:
    orders = [make_order(status="CANCELLED"), make_order(ticker="TSLA_US_EQ")]
    assert tickers_with_open_orders(orders, {"AAPL_US_EQ": "AAPL"}) == set()


def test_order_filled_today_counts_by_fill_time() -> None:
    order = HistoricalOrder.model_validate(
        {
            "id": 1,
            "ticker": "AAPL_US_EQ",
            "type": "LIMIT",
            "status": "FILLED",
            "createdAt": OLD,
            "filledAt": RECENT,
        }
    )
    assert count_filled_orders_since([order], CUTOFF) == 1


class FakeCycleClient(FakeClient):
    pending_orders = [make_order(7, createdAt="2020-01-01T09:00:00Z")]

    def __init__(self, **_: Any) -> None:
        super().__init__()
        CYCLE_CLIENTS.append(self)

    async def __aenter__(self) -> FakeCycleClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def get_account_summary(self) -> Any:
        return SimpleNamespace(
            currency="GBP",
            cash=SimpleNamespace(available_to_trade=Decimal("500")),
            investments=SimpleNamespace(current_value=Decimal("1000")),
        )

    async def get_positions(self) -> list[Any]:
        return []

    async def get_order_history(self, limit: int = 50) -> list[HistoricalOrder]:
        return []

    async def get_all_orders(self) -> list[Order]:
        return self.pending_orders


class FakeProvider:
    fetch_error: Exception | None = None

    async def fetch_multiple(self, tickers: list[Any], period_days: int) -> dict[str, Any]:
        if self.fetch_error:
            raise self.fetch_error
        return {}

    async def fetch_fx_rates_async(self, currencies: set[str], account: str) -> dict[str, float]:
        return {}


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, text: str) -> bool:
        self.messages.append(text)
        return True


CYCLE_CLIENTS: list[FakeCycleClient] = []


@pytest.fixture
def notifier(monkeypatch: pytest.MonkeyPatch) -> FakeNotifier:
    fake = FakeNotifier()
    CYCLE_CLIENTS.clear()
    monkeypatch.setenv("T212_API_KEY", "key")
    monkeypatch.setenv("T212_API_SECRET", "secret")
    monkeypatch.setattr(main, "Trading212Client", FakeCycleClient)
    monkeypatch.setattr(main, "YahooFinanceProvider", FakeProvider)
    monkeypatch.setattr(TelegramNotifier, "from_env", classmethod(lambda cls: fake))
    monkeypatch.setattr(main, "is_blackout", lambda *_: False)
    monkeypatch.setattr(
        main,
        "load_schedules_config",
        lambda: {"sessions": {"eu_morning": {"markets": ["UK"], "enabled": True}}},
    )
    return fake


async def test_cycle_notifies_cancelled_orders(notifier: FakeNotifier) -> None:
    await main.run_trading_cycle("eu_morning", dry_run=False)

    assert CYCLE_CLIENTS[0].cancelled == [7]
    assert notifier.messages[0].startswith("T2-D2 cancelled 1 expired order\nAAPL_US_EQ: 1.5")
    assert "no trades today" in notifier.messages[1]


async def test_cycle_dry_run_reports_without_cancelling(notifier: FakeNotifier) -> None:
    await main.run_trading_cycle("eu_morning", dry_run=True)

    assert CYCLE_CLIENTS[0].cancelled == []
    assert notifier.messages[0].startswith("[DRY RUN] T2-D2 would cancel 1 expired order")


async def test_cycle_notifies_cancellations_before_market_data_failure(
    notifier: FakeNotifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeProvider, "fetch_error", TimeoutError("timed out"))

    with pytest.raises(TimeoutError):
        await main.run_trading_cycle("eu_morning", dry_run=False)

    assert notifier.messages[0].startswith("T2-D2 cancelled 1 expired order")


async def test_cycle_sends_no_cancellation_message_when_nothing_expired(
    notifier: FakeNotifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeCycleClient, "pending_orders", [])

    await main.run_trading_cycle("eu_morning", dry_run=False)

    assert not any("cancel" in message for message in notifier.messages)
