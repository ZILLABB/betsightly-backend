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

from sqlalchemy import (Column, Integer, String, Text, DateTime, Boolean,
                        UniqueConstraint)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base, SessionLocal

logger = logging.getLogger(__name__)

# What a delivery row is about. Kept as constants so the claim and the lookup
# can never drift apart into two spellings of the same notification.
KIND_PREDICTIONS_READY = "predictions_ready"
KIND_RESULTS_UPDATED = "results_updated"

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


class NotificationDelivery(Base):
    """One row per notification we have decided to send.

    Duplicate alerts were guarded by a module-level dict, which lives in
    process memory and dies with the process. Render starts a new process on
    every deploy, so the guard reset and the same alert went out again — a
    notification on every push, and one per restart after a crash. The two
    other schedules in this project already key their guards on the database
    for exactly this reason; this is the third and the last one that did not.

    Keyed per channel rather than per notification, so a Telegram outage can
    be retried without re-sending the web push that already arrived.
    """

    __tablename__ = "notification_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    publish_date = Column(String(10), nullable=False, index=True)
    channel = Column(String(32), nullable=False)
    kind = Column(String(48), nullable=False)
    status = Column(String(16), nullable=False, default="claimed")
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("publish_date", "channel", "kind",
                         name="uq_notification_once_per_day"),
    )


def claim_delivery(publish_date: str, channel: str, kind: str) -> bool:
    """Take the right to send. True only for the caller that wins.

    Claimed *before* the send rather than recorded after it. A crash between
    claiming and sending loses one notification; recording afterwards would
    instead resend on every restart until it happened to succeed, which is
    the failure being fixed. Missing one is the better direction to fail in.
    """
    db = None
    try:
        db = SessionLocal()
        row = NotificationDelivery(
            publish_date=publish_date, channel=channel, kind=kind,
            status="claimed",
        )
        db.add(row)
        db.commit()
        return True
    except IntegrityError:
        if db: db.rollback()
        logger.info(
            f"notification {kind}/{channel} for {publish_date} already sent")
        return False
    except Exception as e:
        # A database that cannot be reached must not become a reason to spam.
        if db: db.rollback()
        logger.error(f"notification claim failed ({kind}/{channel}): {e}")
        return False
    finally:
        if db:
            db.close()


def record_delivery(publish_date: str, channel: str, kind: str,
                    status: str, detail: str = "") -> None:
    """Update a claimed row with what actually happened."""
    db = None
    try:
        db = SessionLocal()
        row = db.query(NotificationDelivery).filter(
            NotificationDelivery.publish_date == publish_date,
            NotificationDelivery.channel == channel,
            NotificationDelivery.kind == kind,
        ).first()
        if row:
            row.status = status
            row.detail = (detail or "")[:500]
            db.commit()
    except Exception as e:
        if db: db.rollback()
        logger.debug(f"notification bookkeeping failed: {e}")
    finally:
        if db:
            db.close()


def delivery_log(limit: int = 40) -> List[Dict[str, Any]]:
    """Recent notification decisions, for the admin view and health checks."""
    db = None
    try:
        db = SessionLocal()
        rows = (db.query(NotificationDelivery)
                  .order_by(NotificationDelivery.id.desc())
                  .limit(limit).all())
        return [{
            "publish_date": r.publish_date, "channel": r.channel,
            "kind": r.kind, "status": r.status, "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
    except Exception as e:
        logger.warning(f"notification log unavailable: {e}")
        return []
    finally:
        if db:
            db.close()


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
    """Fire notifications to all channels when new predictions are ready.

    Refuses to announce an empty card. The count used to come from the retired
    pipeline, which has produced nothing for weeks, so every alert read
    "0 picks for today" while the real card was full. A notification that
    cannot state a real number is worse than no notification, so it is simply
    not sent.
    """
    if not predictions_count or predictions_count <= 0:
        logger.info("Skipping prediction alert: nothing published to announce")
        return

    available = [k.replace("_", " ").title() for k, v in categories.items() if v]
    cats_text = ", ".join(available) if available else "Predictions"

    title = "New Predictions Ready!"
    plural = "pick" if predictions_count == 1 else "picks"
    body = f"{predictions_count} {plural} for {prediction_date}. Categories: {cats_text}"

    # Each channel is claimed on its own. Claiming both together would mean a
    # Telegram outage either loses the retry or resends the web push that
    # already arrived; separately, only the channel that failed is retried.
    if claim_delivery(prediction_date, "web_push", KIND_PREDICTIONS_READY):
        send_push_to_all(title=title, body=body, url="/predictions")
        record_delivery(prediction_date, "web_push", KIND_PREDICTIONS_READY,
                        "sent", f"{predictions_count} picks")

    if claim_delivery(prediction_date, "telegram_dm", KIND_PREDICTIONS_READY):
        tg_message = (
            f"<b>New Predictions Ready!</b>\n\n"
            f"<b>{predictions_count}</b> picks for <b>{prediction_date}</b>\n"
            f"Categories: {cats_text}\n\n"
            f"Check them out at betsightly.com/predictions"
        )
        send_telegram_dm_to_all(tg_message)
        record_delivery(prediction_date, "telegram_dm", KIND_PREDICTIONS_READY,
                        "sent", f"{predictions_count} picks")


def notify_results_updated(date: str, won: int, lost: int):
    """Fire notifications when results are updated.

    Nothing calls this yet. Guarded anyway: results settle on an hourly loop,
    so the first caller to wire it up would otherwise announce the same day
    every hour, which is the same failure this change exists to end.
    """
    if not claim_delivery(date, "web_push", KIND_RESULTS_UPDATED):
        return
    title = "Results Updated"
    body = f"Results for {date}: {won}W - {lost}L"
    send_push_to_all(title=title, body=body, url="/results")
    record_delivery(date, "web_push", KIND_RESULTS_UPDATED,
                    "sent", f"{won}W-{lost}L")
