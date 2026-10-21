"""Telegram notifications for executed trades, or a note when there are none.

Enabled when both ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` are set.
A failed notification is logged and never stops the trading run.
"""
from __future__ import annotations

import os

import httpx
import structlog
from t2d2_algo.links import instrument_url
from t2d2_algo.strategies.base import TradeDecision

API_BASE_URL = "https://api.telegram.org"

log = structlog.get_logger()


def format_trade_message(decision: TradeDecision, session: str, dry_run: bool) -> str:
    """Build the plain-text Telegram message for one executed trade.

    Args:
        decision: The executed trade.
        session: Session that placed the trade.
        dry_run: Whether the order was only simulated.

    Returns:
        Message text; Telegram turns the instrument URL into a tappable link.
    """
    prefix = "[DRY RUN] " if dry_run else ""
    strategy = f" [{decision.strategy}]" if decision.strategy else ""
    lines = [
        f"{prefix}T2-D2 BUY {decision.ticker}{strategy}",
        f"£{decision.trade_value_gbp:.2f} ({decision.quantity} shares)",
    ]
    if decision.limit_price:
        lines.append(f"Limit {decision.limit_price:.2f} {decision.currency or ''}".rstrip())
    lines.append(
        f"Daily {decision.daily_change_pct:+.2f}% | Weekly {decision.weekly_change_pct:+.2f}%"
    )
    lines.append(f"Session: {session}")
    url = instrument_url(decision.t212_ticker or decision.ticker)
    if url:
        lines.append(url)
    return "\n".join(lines)


def format_no_trades_message(session: str, dry_run: bool) -> str:
    """Build the Telegram message sent when a session places no trades.

    Args:
        session: Session that ran.
        dry_run: Whether the run was a dry run.

    Returns:
        Message text.
    """
    prefix = "[DRY RUN] " if dry_run else ""
    return f"{prefix}T2-D2: no trades today\nSession: {session}"


def format_daily_wrap_message(
    cash_gbp: float,
    invested_gbp: float,
    positions: int,
    orders_filled_today: int | None,
) -> str:
    """Build the end-of-day portfolio summary message.

    Args:
        cash_gbp: Free cash available to trade.
        invested_gbp: Current value of all positions.
        positions: Number of open positions.
        orders_filled_today: Orders filled today, or None if order history was unavailable.

    Returns:
        Message text.
    """
    lines = [
        "T2-D2 daily wrap",
        f"Cash: £{cash_gbp:,.2f} | Invested: £{invested_gbp:,.2f} | Positions: {positions}",
    ]
    if orders_filled_today is not None:
        lines.append(f"Orders filled today: {orders_filled_today}")
    return "\n".join(lines)


class TelegramNotifier:
    """Sends messages to one Telegram chat via the Bot API."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = f"{API_BASE_URL}/bot{bot_token}"
        self._chat_id = chat_id
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_env(cls) -> TelegramNotifier | None:
        """Create a notifier from the environment, or None if Telegram is not configured."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return None
        return cls(bot_token=token, chat_id=chat_id)

    async def send(self, text: str) -> bool:
        """Send a message, logging (not raising) on failure.

        Args:
            text: Plain-text message body.

        Returns:
            True if Telegram accepted the message.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    "/sendMessage", json={"chat_id": self._chat_id, "text": text}
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # The request URL contains the bot token, so never log the exception text
            log.warning("telegram_send_failed", status_code=e.response.status_code)
            return False
        except httpx.HTTPError as e:
            log.warning("telegram_send_failed", error_type=type(e).__name__)
            return False
        return True
