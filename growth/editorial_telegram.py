"""Send one distinct Telegram code-board update after each verified manual fill.

Daily Telegram's 08:00 WAT code board cannot predict a manual tier added at
noon. This event is emitted only AFTER the database commits the full verified
SportyBet ticket; publication dedup and retry use the existing growth outbox.
"""
from __future__ import annotations

import hashlib
import logging
import threading

LOG = logging.getLogger(__name__)
LABELS = {"banker":"Banker", "2_odds":"2 Odds", "5_odds":"5 Odds",
          "10_odds":"10 Odds", "over_1_5":"Over 1.5"}


def message_for_manual(date: str, tier: str, payload: dict) -> dict:
    booking = payload.get("booking") or {}
    if (tier not in LABELS or not payload.get("editorial_manual")
            or booking.get("readback_validation") != "PASSED"
            or booking.get("booking_status") != "FULL"
            or not booking.get("share_code")):
        raise ValueError("Cannot announce an unverified manual booking")
    games = payload.get("games") or []
    if not games or len(booking.get("final_booked_legs") or []) != len(games):
        raise ValueError("Manual share code does not represent every published leg")
    lines = [
        "📌 *BetSightly verified manual slip*",
        f"_{date} · {LABELS[tier]}_",
        "",
        "Admin-curated replacement for an empty automatic tier.",
        "This is NOT a model-scored prediction.",
        "",
    ]
    for game in games[:20]:
        name = str(game.get("home_team") or "") + " vs " + str(game.get("away_team") or "")
        choice = str(game.get("prediction") or game.get("market") or "")
        # Plain lines avoid broken Telegram Markdown for team and market names.
        lines.append(f"• {name} — {choice}")
    lines += [
        "",
        f"🎯 Published odds: {float(payload.get('total_odds') or 0):.2f}x",
        f"🎟️ SportyBet code: {booking['share_code']}",
        "",
        "Prices and availability can change. No win is guaranteed.",
        "Informational predictions only. 18+; stake responsibly.",
    ]
    return {"text":"\n".join(lines), "parse_mode":None,
            "url":"https://betsightly.com/predictions"}


def queue_published_manual(date: str, tier: str, payload: dict) -> dict:
    """Persist an idempotent event before attempting external transmission."""
    from growth import store
    from growth.models import channel_auto_publishes
    from growth.publishers.telegram import send
    msg = message_for_manual(date, tier, payload)
    item = {
        "date":date, "template":f"manual_{tier}", "platform":"telegram",
        "payload":msg, "url":msg["url"],
        "hash":hashlib.sha256(
            f"betsightly|manual|telegram|{date}|{tier}".encode()
        ).hexdigest(),
    }
    saved = store.store_items([item])
    if not channel_auto_publishes("telegram"):
        return {"queued": True, "sent": False, "reason": "not_enabled_for_auto_post"}
    content_id = (saved.get("ids") or [None])[0]
    if not content_id:
        return {"queued": False, "sent": False, "reason": "outbox_write_failed"}
    def post():
        try:
            status = store.publish_one(content_id, send)
            if not status.get("ok") and status.get("reason") != "already published or in flight":
                LOG.warning("Manual Telegram delivery failed: %s",
                            str(status.get("reason") or "unknown")[:90])
        except Exception as exc:
            LOG.warning("Manual Telegram dispatch exception: %s", type(exc).__name__)
    threading.Thread(target=post, name="manual-telegram-delivery",
                     daemon=True).start()
    return {"queued": True, "sent": False, "reason": "sending_async"}
