"""Tests for WebhookNotifier delivery and URL validation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from t2d2_notifier import TradeNotification, WebhookNotifier

URL = "https://hooks.example.com/t2d2"


def make_notification() -> TradeNotification:
    return TradeNotification(
        ticker="AAPL",
        action="BUY",
        value_gbp=25.0,
        price=180.5,
        daily_change_pct=-2.1,
        weekly_change_pct=-4.3,
        session="us_morning",
        strategy_mode="mild",
        dry_run=True,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/t2d2",
        "https://localhost/hook",
        "https://169.254.169.254/latest",
        "https://10.0.0.5/hook",
    ],
)
def test_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        WebhookNotifier(webhook_url=url)


def test_no_url_skips_post() -> None:
    with patch("t2d2_notifier.webhook.httpx.post") as post:
        notifier = WebhookNotifier()
        notifier.send_trade(make_notification())
        notifier.send_session_report("us_morning", 1, 25.0, 975.0)
    post.assert_not_called()


def test_send_trade_posts_payload() -> None:
    with patch("t2d2_notifier.webhook.httpx.post") as post:
        WebhookNotifier(webhook_url=URL).send_trade(make_notification())
    payload = post.call_args.kwargs["json"]
    assert post.call_args.args[0] == URL
    assert payload["title"] == "[DRY RUN] T2-D2: BUY AAPL"
    assert payload["ticker"] == "AAPL"
    assert payload["dry_run"] == "true"


def test_send_session_report_posts_payload() -> None:
    with patch("t2d2_notifier.webhook.httpx.post") as post:
        WebhookNotifier(webhook_url=URL).send_session_report("eu_morning", 2, 50.0, 950.0)
    payload = post.call_args.kwargs["json"]
    assert payload["action"] == "REPORT"
    assert payload["trades_count"] == "2"
    assert payload["cash_remaining"] == "950.0"


def test_delivery_failure_is_logged_not_raised() -> None:
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock()
    )
    with patch("t2d2_notifier.webhook.httpx.post", return_value=response):
        WebhookNotifier(webhook_url=URL).send_trade(make_notification())
