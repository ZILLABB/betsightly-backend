"""
Push notification subscription endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.push_notification_service import (
    PushSubscription,
    TelegramDMSubscription,
    get_vapid_public_key,
)

router = APIRouter()


class WebPushSubscribeRequest(BaseModel):
    endpoint: str
    keys: dict  # {"p256dh": "...", "auth": "..."}
    user_agent: str | None = None


class TelegramSubscribeRequest(BaseModel):
    chat_id: str
    username: str | None = None


# ── VAPID public key (frontend needs this to subscribe) ──────

@router.get("/vapid-public-key")
def vapid_public_key():
    key = get_vapid_public_key()
    if not key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": key}


# ── Web Push subscription ────────────────────────────────────

@router.post("/web-push/subscribe")
def web_push_subscribe(req: WebPushSubscribeRequest, db: Session = Depends(get_db)):
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == req.endpoint
    ).first()

    if existing:
        existing.active = True
        existing.p256dh_key = req.keys.get("p256dh", existing.p256dh_key)
        existing.auth_key = req.keys.get("auth", existing.auth_key)
        db.commit()
        return {"status": "updated", "id": existing.id}

    sub = PushSubscription(
        endpoint=req.endpoint,
        p256dh_key=req.keys.get("p256dh", ""),
        auth_key=req.keys.get("auth", ""),
        user_agent=req.user_agent,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"status": "subscribed", "id": sub.id}


@router.post("/web-push/unsubscribe")
def web_push_unsubscribe(req: WebPushSubscribeRequest, db: Session = Depends(get_db)):
    sub = db.query(PushSubscription).filter(
        PushSubscription.endpoint == req.endpoint
    ).first()
    if sub:
        sub.active = False
        db.commit()
    return {"status": "unsubscribed"}


# ── Telegram DM subscription ────────────────────────────────

@router.post("/telegram/subscribe")
def telegram_subscribe(req: TelegramSubscribeRequest, db: Session = Depends(get_db)):
    existing = db.query(TelegramDMSubscription).filter(
        TelegramDMSubscription.chat_id == req.chat_id
    ).first()

    if existing:
        existing.active = True
        existing.username = req.username or existing.username
        db.commit()
        return {"status": "updated", "id": existing.id}

    sub = TelegramDMSubscription(
        chat_id=req.chat_id,
        username=req.username,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"status": "subscribed", "id": sub.id}


@router.post("/telegram/unsubscribe")
def telegram_unsubscribe(req: TelegramSubscribeRequest, db: Session = Depends(get_db)):
    sub = db.query(TelegramDMSubscription).filter(
        TelegramDMSubscription.chat_id == req.chat_id
    ).first()
    if sub:
        sub.active = False
        db.commit()
    return {"status": "unsubscribed"}
