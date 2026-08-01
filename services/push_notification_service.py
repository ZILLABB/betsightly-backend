"""
Push Notification Service
Handles Web Push (VAPID) and Telegram DM notifications.
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import Session

from database import Base, SessionLocal

logger = logging.getLogger(__name__)

# ── DB Model ─────────────────────────────────────────────────

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh_key = Column(Text, nullable=False)
    auth_key = Column(Text, nullable=False)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)


class TelegramDMSubscription(Base):
    __tablename__ = "telegram_dm_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String(64), nullable=False, unique=True)
    username = Column(String(255), nullable=True)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)


# ── VAPID Config ─────────────────────────────────────────────

def _get_vapid_keys() -> Dict[str, str]:
    private_key = os.getenv("VAPID_PRIVATE_KEY", "")
    public_key = os.getenv("VAPID_PUBLIC_KEY", "")
    contact = os.getenv("VAPID_CONTACT", "mailto:admin@betsightly.com")
    return {"private_key": private_key, "public_key": public_key, "contact": contact}


def get_vapid_public_key() -> str:
    return _get_vapid_keys()["public_key"]


# ── Web Push ─────────────────────────────────────────────────

def _send_web_push(subscription_info: Dict, payload: str) -> bool:
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush not installed — skipping web push")
        return False

    keys = _get_vapid_keys()
    if not keys["private_key"]:
        logger.warning("VAPID_PRIVATE_KEY not set — skipping web push")
        return False

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=keys["private_key"],
            vapid_claims={"sub": keys["contact"]},
            timeout=10,
        )
        return True
    except Exception as e:
        error_msg = str(e)
        if "410" in error_msg or "404" in error_msg:
            return False  # subscription expired — caller should deactivate
        logger.error(f"Web push failed: {error_msg}")
        return False


def send_push_to_all(title: str, body: str, url: str = "/predictions", data: Optional[Dict] = None):
    """Send push notification to all active web subscribers. Runs in background thread."""

    def _do_send():
        db = SessionLocal()
        try:
            subs = db.query(PushSubscription).filter(PushSubscription.active == True).all()
            if not subs:
                return

            payload = json.dumps({
                "title": title,
                "body": body,
                "url": url,
                "icon": "/pwa-192x192.png",
                "badge": "/pwa-192x192.png",
                "data": data or {},
                "timestamp": datetime.utcnow().isoformat(),
            })

            expired_ids = []
            sent = 0
            for sub in subs:
                sub_info = {
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
                }
                ok = _send_web_push(sub_info, payload)
                if ok:
                    sent += 1
                else:
                    expired_ids.append(sub.id)

            if expired_ids:
                db.query(PushSubscription).filter(
                    PushSubscription.id.in_(expired_ids)
                ).update({"active": False}, synchronize_session=False)
                db.commit()

            logger.info(f"Web push sent to {sent}/{len(subs)} subscribers ({len(expired_ids)} expired)")
        except Exception as e:
            logger.error(f"Error sending web push: {e}")
        finally:
            db.close()

    threading.Thread(target=_do_send, daemon=True).start()


# ── Telegram DM ──────────────────────────────────────────────

def send_telegram_dm_to_all(message: str):
    """Send Telegram DM to all subscribed users. Runs in background thread."""

    def _do_send():
        import asyncio

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set — skipping DM notifications")
            return

        db = SessionLocal()
        try:
            subs = db.query(TelegramDMSubscription).filter(
                TelegramDMSubscription.active == True
            ).all()
            if not subs:
                return

            async def _send_all():
                from telegram import Bot
                bot = Bot(token=bot_token)
                sent = 0
                deactivated = []
                for sub in subs:
                    try:
                        await bot.send_message(
                            chat_id=int(sub.chat_id),
                            text=message,
                            parse_mode="HTML",
                        )
                        sent += 1
                    except Exception as e:
                        if "blocked" in str(e).lower() or "not found" in str(e).lower():
                            deactivated.append(sub.id)
                        logger.warning(f"DM to {sub.chat_id} failed: {e}")

                if deactivated:
                    db.query(TelegramDMSubscription).filter(
                        TelegramDMSubscription.id.in_(deactivated)
                    ).update({"active": False}, synchronize_session=False)
                    db.commit()

                logger.info(f"Telegram DMs sent to {sent}/{len(subs)} subscribers")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_send_all())
            loop.close()

        except Exception as e:
            logger.error(f"Error sending Telegram DMs: {e}")
        finally:
            db.close()

    threading.Thread(target=_do_send, daemon=True).start()


# ── Combined Notification Trigger ────────────────────────────

def notify_predictions_ready(
    prediction_date: str,
    predictions_count: int,
    categories: Dict[str, bool],
):
    """Fire notifications to all channels when new predictions are ready."""
    available = [k.replace("_", " ").title() for k, v in categories.items() if v]
    cats_text = ", ".join(available) if available else "Predictions"

    title = "New Predictions Ready!"
    body = f"{predictions_count} picks for {prediction_date}. Categories: {cats_text}"

    send_push_to_all(title=title, body=body, url="/predictions")

    tg_message = (
        f"<b>New Predictions Ready!</b>\n\n"
        f"<b>{predictions_count}</b> picks for <b>{prediction_date}</b>\n"
        f"Categories: {cats_text}\n\n"
        f"Check them out at betsightly.com/predictions"
    )
    send_telegram_dm_to_all(tg_message)


def notify_results_updated(date: str, won: int, lost: int):
    """Fire notifications when results are updated."""
    title = "Results Updated"
    body = f"Results for {date}: {won}W - {lost}L"
    send_push_to_all(title=title, body=body, url="/results")
