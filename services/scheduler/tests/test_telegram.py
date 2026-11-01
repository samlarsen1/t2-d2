"""Tests for Telegram trade notifications."""
from __future__ import annotations

import json

import httpx
import pytest
from scheduler.telegram import (
    TelegramNotifier,
    format_cancelled_orders_message,
    format_daily_wrap_message,
    format_no_trades_message,
    format_trade_message,
)
from t2d2_algo.strategies.base import TradeDecision
from t2d2_client.models import Order

TOKEN = "123456:TEST-token"


def make_trade(**overrides: object) -> TradeDecision:
    defaults = dict(
        ticker="TSLA",
        should_trade=True,
        trade_value_gbp=50.0,
        reason="dip",
        daily_change_pct=-3.21,
        weekly_change_pct=-6.5,
        rsi=30.0,
        current_price=250.0,
        limit_price=248.75,
        t212_ticker="TSLA_US_EQ",
        strategy="moderate",
        quantity=0.2671,
        currency="USD",
    )
    defaults.update(overrides)
    return TradeDecision(**defaults)  # type: ignore[arg-type]


def test_format_trade_message() -> None:
    text = format_trade_message(make_trade(), "us_morning", dry_run=False)

    assert text.splitlines() == [
        "T2-D2 BUY TSLA [moderate]",
        "£50.00 (0.2671 shares)",
        "Limit 248.75 USD",
        "Daily -3.21% | Weekly -6.50%",
        "Session: us_morning",
        "https://www.trading212.com/trading-instruments/invest/TSLA.US",
    ]


def test_format_trade_message_dry_run_market_order() -> None:
    text = format_trade_message(make_trade(limit_price=None), "us_morning", dry_run=True)

    assert text.startswith("[DRY RUN] T2-D2 BUY TSLA")
    assert "Limit" not in text


def test_format_no_trades_message() -> None:
    assert format_no_trades_message("us_afternoon", dry_run=False) == (
        "T2-D2: no trades today\nSession: us_afternoon"
    )
    assert format_no_trades_message("us_afternoon", dry_run=True).startswith(
        "[DRY RUN] T2-D2: no trades today"
    )


def make_order(ticker: str, **overrides: object) -> Order:
    payload = {
        "id": 1,
        "ticker": ticker,
        "type": "LIMIT",
        "side": "BUY",
        "status": "NEW",
        "initiatedFrom": "API",
        "quantity": 1.5,
        "limitPrice": 180.0,
        "currency": "USD",
        "createdAt": "2026-10-20T09:00:00Z",
    }
    return Order.model_validate({**payload, **overrides})


def test_format_cancelled_orders_message_lists_each_order() -> None:
    orders = [
        make_order("AAPL_US_EQ"),
        make_order("ITMl_EQ", quantity=45.1297, limitPrice=74.77, currency="GBX", filledQuantity=5),
    ]

    assert format_cancelled_orders_message(orders, "eu_morning", dry_run=False).splitlines() == [
        "T2-D2 cancelled 2 expired orders",
        "AAPL_US_EQ: 1.5 shares @ limit 180.00 USD, placed 2026-10-20",
        "ITMl_EQ: 45.1297 shares @ limit 74.77 GBX (5 filled), placed 2026-10-20",
        "Session: eu_morning",
    ]


def test_format_cancelled_orders_message_dry_run_single_order() -> None:
    text = format_cancelled_orders_message([make_order("AAPL_US_EQ")], "eu_morning", dry_run=True)

    assert text.startswith("[DRY RUN] T2-D2 would cancel 1 expired order\n")


def test_format_daily_wrap_message() -> None:
    text = format_daily_wrap_message(1276.3, 69192.17, 32, orders_filled_today=2)

    assert text.splitlines() == [
        "T2-D2 daily wrap",
        "Cash: £1,276.30 | Invested: £69,192.17 | Positions: 32",
        "Orders filled today: 2",
    ]


def test_format_daily_wrap_message_without_order_history() -> None:
    text = format_daily_wrap_message(1276.3, 69192.17, 32, orders_filled_today=None)

    assert "Orders filled today" not in text


def test_from_env_requires_token_and_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert TelegramNotifier.from_env() is None

    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    assert TelegramNotifier.from_env() is not None


async def test_send_posts_to_bot_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    notifier = TelegramNotifier(TOKEN, "987654321", transport=httpx.MockTransport(handler))

    assert await notifier.send("hello") is True
    assert str(requests[0].url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert json.loads(requests[0].content) == {"chat_id": "987654321", "text": "hello"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}),
        httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "parameters": {"retry_after": 5}},
        ),
        httpx.Response(502, text="Bad Gateway"),
    ],
)
async def test_send_returns_false_on_http_error(
    response: httpx.Response, capsys: pytest.CaptureFixture[str]
) -> None:
    notifier = TelegramNotifier(
        TOKEN, "987654321", transport=httpx.MockTransport(lambda _: response)
    )

    assert await notifier.send("hello") is False
    assert TOKEN not in capsys.readouterr().out


async def test_send_returns_false_on_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    notifier = TelegramNotifier(TOKEN, "987654321", transport=httpx.MockTransport(handler))

    assert await notifier.send("hello") is False
    assert TOKEN not in capsys.readouterr().out
