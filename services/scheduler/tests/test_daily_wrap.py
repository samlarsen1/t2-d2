"""Tests for counting today's filled orders in the daily wrap."""
from __future__ import annotations

from datetime import UTC, datetime

from scheduler.main import count_filled_orders_since
from t2d2_client.models import HistoricalOrder


def make_order(order_id: int, status: str, created_at: str | None) -> HistoricalOrder:
    return HistoricalOrder.model_validate(
        {
            "id": order_id,
            "ticker": "TSLA_US_EQ",
            "type": "LIMIT",
            "status": status,
            "createdAt": created_at,
        }
    )


def test_count_filled_orders_since() -> None:
    cutoff = datetime(2026, 10, 21, tzinfo=UTC)
    orders = [
        make_order(1, "FILLED", "2026-10-21T14:31:02.000Z"),
        make_order(2, "PARTIALLY_FILLED", "2026-10-21T09:05:00.000Z"),
        make_order(3, "CANCELLED", "2026-10-21T15:00:00.000Z"),
        make_order(4, "FILLED", "2026-10-20T20:59:59.000Z"),
        make_order(5, "FILLED", None),
    ]

    assert count_filled_orders_since(orders, cutoff) == 2


def test_count_filled_orders_since_empty() -> None:
    assert count_filled_orders_since([], datetime(2026, 10, 21, tzinfo=UTC)) == 0
