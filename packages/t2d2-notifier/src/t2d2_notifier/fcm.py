"""
Firebase Cloud Messaging (FCM) push notification dispatcher.

Sends trade notifications to the T2-D2 Android app via FCM topics.
Also supports optional webhook delivery for external integrations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("firebase-admin not installed; FCM notifications disabled")


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


class FCMNotifier:
    """Sends push notifications via Firebase Cloud Messaging."""

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        topic: str = "t2d2-trades",
        webhook_url: str | None = None,
    ) -> None:
        self.topic = topic
        self.webhook_url = webhook_url
        self._initialized = False

        if not FIREBASE_AVAILABLE:
            return

        if credentials_path and Path(credentials_path).exists() and not self._initialized:
            cred = credentials.Certificate(str(credentials_path))
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            self._initialized = True
        elif credentials_path and not Path(credentials_path).exists():
            logger.warning(
                "Firebase credentials not found at %s — notifications disabled", credentials_path
            )

    def send_trade(self, notification: TradeNotification) -> None:
        """Send a trade notification via FCM topic broadcast."""
        logger.info("Dispatching notification: %s", notification.title())

        if FIREBASE_AVAILABLE and self._initialized:
            self._send_fcm(notification)
        else:
            logger.info(
                "FCM not available — notification logged only: %s %s",
                notification.title(),
                notification.body(),
            )

        if self.webhook_url:
            self._send_webhook(notification)

    def _send_fcm(self, notification: TradeNotification) -> None:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=notification.title(),
                    body=notification.body(),
                ),
                data=notification.to_data(),
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="t2d2_trades",
                        icon="ic_t2d2",
                        color="#00C853",
                    ),
                ),
                topic=self.topic,
            )
            response = messaging.send(message)
            logger.info("FCM message sent: %s", response)
        except Exception as e:
            logger.error("FCM send failed: %s", e)

    def _send_webhook(self, notification: TradeNotification) -> None:
        payload = {
            "title": notification.title(),
            "body": notification.body(),
            **notification.to_data(),
        }
        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=10.0)  # type: ignore[arg-type]
            resp.raise_for_status()
            logger.info("Webhook delivered to %s", self.webhook_url)
        except Exception as e:
            logger.warning("Webhook delivery failed: %s", e)

    def send_session_report(
        self,
        session: str,
        trades_count: int,
        total_deployed: float,
        cash_remaining: float,
    ) -> None:
        """Send an end-of-session summary notification."""
        TradeNotification(
            ticker="PORTFOLIO",
            action="REPORT",
            value_gbp=total_deployed,
            price=0.0,
            daily_change_pct=0.0,
            weekly_change_pct=0.0,
            session=session,
            strategy_mode="",
        )
        # Override body for report
        if FIREBASE_AVAILABLE and self._initialized:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=f"T2-D2 Session Report: {session}",
                        body=(
                            f"{trades_count} trade(s) | "
                            f"£{total_deployed:.2f} deployed | "
                            f"£{cash_remaining:.2f} cash remaining"
                        ),
                    ),
                    data={
                        "action": "REPORT",
                        "session": session,
                        "trades_count": str(trades_count),
                        "total_deployed": str(round(total_deployed, 2)),
                        "cash_remaining": str(round(cash_remaining, 2)),
                    },
                    topic=self.topic,
                )
                messaging.send(message)
            except Exception as e:
                logger.error("Session report FCM send failed: %s", e)
