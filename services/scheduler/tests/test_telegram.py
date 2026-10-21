"""Tests for Telegram trade notifications."""
from __future__ import annotations

import json

import httpx
import pytest
from scheduler.telegram import TelegramNotifier, format_trade_message
from t2d2_algo.strategies.base import TradeDecision

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
