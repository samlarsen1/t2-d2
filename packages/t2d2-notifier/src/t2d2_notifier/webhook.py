"""
Webhook notification dispatcher.

Logs every trade notification locally and, if a webhook URL is configured,
POSTs it as JSON for external integrations (e.g. Slack, Discord, ntfy).
"""
from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"https"}
_BLOCKED_HOSTS = {
    "localhost",
    "169.254.169.254",  # cloud metadata service
    "metadata.google.internal",
}


def _validate_webhook_url(url: str) -> None:
    """Raise ValueError if the URL is not safe to POST to."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Webhook URL scheme must be https, got: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("Webhook URL has no host")
    if host.lower() in _BLOCKED_HOSTS:
        raise ValueError(f"Webhook URL host is blocked: {host!r}")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError(f"Webhook URL resolves to a non-public IP: {host!r}")
    except ValueError as exc:
        # ip_address() raises ValueError for hostnames — only re-raise our own checks
        if "Webhook URL" in str(exc):
            raise


@dataclass
class TradeNotification:
    ticker: str
    action: str                  # "BUY" | "SELL" | "REPORT"
    value_gbp: float
    price: float
    daily_change_pct: float
    weekly_change_pct: float
    session: str
    strategy_mode: str
    dry_run: bool = False

    def title(self) -> str:
        prefix = "[DRY RUN] " if self.dry_run else ""
        return f"{prefix}T2-D2: {self.action} {self.ticker}"

    def body(self) -> str:
        return (
            f"£{self.value_gbp:.2f} @ {self.price:.4f} | "
            f"1d: {self.daily_change_pct:+.2f}% | "
            f"5d: {self.weekly_change_pct:+.2f}% | "
            f"{self.session} [{self.strategy_mode}]"
        )

    def to_data(self) -> dict[str, str]:
        return {
            "ticker": self.ticker,
            "action": self.action,
            "value_gbp": str(round(self.value_gbp, 2)),
            "price": str(self.price),
            "daily_change_pct": str(round(self.daily_change_pct, 2)),
            "weekly_change_pct": str(round(self.weekly_change_pct, 2)),
            "session": self.session,
            "strategy_mode": self.strategy_mode,
            "dry_run": str(self.dry_run).lower(),
        }


class WebhookNotifier:
    """Logs notifications and optionally delivers them to a webhook."""

    def __init__(self, webhook_url: str | None = None) -> None:
        if webhook_url:
            _validate_webhook_url(webhook_url)
        self.webhook_url = webhook_url

    def send_trade(self, notification: TradeNotification) -> None:
        """Log a trade notification and deliver it to the webhook, if configured."""
        logger.info("Notification: %s | %s", notification.title(), notification.body())
        self._post(
            {
                "title": notification.title(),
                "body": notification.body(),
                **notification.to_data(),
            }
        )

    def send_session_report(
        self,
        session: str,
        trades_count: int,
        total_deployed: float,
        cash_remaining: float,
    ) -> None:
        """Log an end-of-session summary and deliver it to the webhook, if configured."""
        title = f"T2-D2 Session Report: {session}"
        body = (
            f"{trades_count} trade(s) | "
            f"£{total_deployed:.2f} deployed | "
            f"£{cash_remaining:.2f} cash remaining"
        )
        logger.info("Notification: %s | %s", title, body)
        self._post(
            {
                "title": title,
                "body": body,
                "action": "REPORT",
                "session": session,
                "trades_count": str(trades_count),
                "total_deployed": str(round(total_deployed, 2)),
                "cash_remaining": str(round(cash_remaining, 2)),
            }
        )

    def _post(self, payload: dict[str, Any]) -> None:
        if not self.webhook_url:
            return
        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=10.0)
            resp.raise_for_status()
            logger.info("Webhook delivered")
        except Exception as e:
            logger.warning("Webhook delivery failed: %s", type(e).__name__)
