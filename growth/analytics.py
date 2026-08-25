"""
Growth analytics — where visitors come from, and which content brings them.

Server-side because the question is attribution, not engagement. `@vercel/analytics`
already counts pageviews; what it cannot answer is "did the Telegram post at
07:30 produce visits", because that needs the campaign parameters joined to
the visit and kept.

Privacy shape, chosen deliberately:

- No cookies, no device ids, no cross-site identifiers.
- A visitor is a daily rotating hash of (IP + user agent + date + secret).
  Salting with the date means yesterday's hash cannot be linked to today's, so
  the store can answer "how many people, from where" without accumulating a
  profile of anyone. It also means "returning visitor" is measurable within a
  day but not across weeks — an honest trade, and the honest direction to err.
- Raw IPs are never stored.
"""

import hashlib
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import func

from database import SessionLocal
from growth.models import GrowthEvent

logger = logging.getLogger(__name__)

EVENT_TYPES = {"pageview", "telegram_click", "cta_click", "registration", "outbound"}

# Traffic we can name, mapped from the referring host when there are no UTM
# parameters. Without this, everything organic lands in "direct" and the
# acquisition breakdown is useless.
REFERRER_SOURCES = {
    "google.": "google", "bing.": "bing", "duckduckgo.": "duckduckgo",
    "t.co": "x", "twitter.com": "x", "x.com": "x",
    "facebook.": "facebook", "fb.": "facebook",
    "instagram.": "instagram", "tiktok.": "tiktok",
    "youtube.": "youtube", "youtu.be": "youtube",
    "t.me": "telegram", "telegram.": "telegram",
    "reddit.": "reddit", "linkedin.": "linkedin",
}


def _visitor_hash(ip: str, user_agent: str, date: str) -> str:
    salt = os.getenv("SECRET_KEY", "betsightly")
    raw = f"{ip}|{user_agent}|{date}|{salt}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _classify_referrer(referrer: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(source, host) inferred from a referrer URL."""
    if not referrer:
        return None, None
    try:
        host = (urlparse(referrer).hostname or "").lower()
    except Exception:
        return None, None
    if not host:
        return None, None
    if "betsightly" in host:
        return None, host          # internal navigation, not acquisition
    for needle, source in REFERRER_SOURCES.items():
        if needle in host:
            return source, host
    return "referral", host


def record(*, event_type: str, path: Optional[str] = None,
           source: Optional[str] = None, medium: Optional[str] = None,
           campaign: Optional[str] = None, content_tag: Optional[str] = None,
           ref: Optional[str] = None, referrer: Optional[str] = None,
           ip: str = "", user_agent: str = "") -> bool:
    """Record one attributed event. Never raises — analytics must not 500 a page."""
    try:
        if event_type not in EVENT_TYPES:
            event_type = "pageview"

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        vhash = _visitor_hash(ip, user_agent, today)

        ref_source, ref_host = _classify_referrer(referrer)
        # Explicit campaign tagging always wins over an inferred referrer:
        # a Telegram link opened via a redirect still came from Telegram.
        source = source or ref_source or "direct"
        medium = medium or ("organic" if ref_source in ("google", "bing", "duckduckgo")
                            else ("referral" if ref_source else "none"))

        db = SessionLocal()
        try:
            seen_today = (
                db.query(GrowthEvent.id)
                .filter(GrowthEvent.event_date == today,
                        GrowthEvent.visitor_hash == vhash)
                .first()
            )
            db.add(GrowthEvent(
                event_date=today,
                event_type=event_type,
                path=(path or "")[:256] or None,
                source=(source or "")[:64] or None,
                medium=(medium or "")[:64] or None,
                campaign=(campaign or "")[:64] or None,
                content_tag=(content_tag or "")[:64] or None,
                ref=(ref or "")[:64] or None,
                visitor_hash=vhash,
                is_new_visitor=seen_today is None,
                referrer_host=(ref_host or "")[:128] or None,
            ))
            db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"growth analytics: record failed ({e})")
        return False


def _range(days: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(0, days - 1))
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def summary(days: int = 7) -> dict:
    """Traffic, acquisition and conversion over the window."""
    start, end = _range(days)
    db = SessionLocal()
    try:
        base = db.query(GrowthEvent).filter(
            GrowthEvent.event_date >= start, GrowthEvent.event_date <= end)

        total_events = base.count()
        pageviews = base.filter(GrowthEvent.event_type == "pageview").count()
        visitors = base.with_entities(
            func.count(func.distinct(GrowthEvent.visitor_hash))).scalar() or 0
        new_visitors = base.filter(GrowthEvent.is_new_visitor.is_(True)).with_entities(
            func.count(func.distinct(GrowthEvent.visitor_hash))).scalar() or 0
        telegram_clicks = base.filter(
            GrowthEvent.event_type == "telegram_click").count()
        registrations = base.filter(
            GrowthEvent.event_type == "registration").count()

        def group(column):
            rows = (
                db.query(column, func.count(GrowthEvent.id))
                .filter(GrowthEvent.event_date >= start, GrowthEvent.event_date <= end)
                .group_by(column)
                .order_by(func.count(GrowthEvent.id).desc())
                .limit(25)
                .all()
            )
            return [{"key": k or "unknown", "count": c} for k, c in rows]

        daily_rows = (
            db.query(GrowthEvent.event_date,
                     func.count(func.distinct(GrowthEvent.visitor_hash)),
                     func.count(GrowthEvent.id))
            .filter(GrowthEvent.event_date >= start, GrowthEvent.event_date <= end)
            .group_by(GrowthEvent.event_date)
            .order_by(GrowthEvent.event_date.asc())
            .all()
        )

        return {
            "window_days": days,
            "start": start,
            "end": end,
            "totals": {
                "events": total_events,
                "pageviews": pageviews,
                "visitors": visitors,
                "new_visitors": new_visitors,
                "returning_visitors": max(0, visitors - new_visitors),
                "telegram_clicks": telegram_clicks,
                "registrations": registrations,
                "telegram_click_rate": (round(telegram_clicks / visitors, 4)
                                        if visitors else None),
                "conversion_rate": (round(registrations / visitors, 4)
                                    if visitors else None),
            },
            "by_source": group(GrowthEvent.source),
            "by_campaign": group(GrowthEvent.campaign),
            "by_content": group(GrowthEvent.content_tag),
            "by_path": group(GrowthEvent.path),
            "by_ref": [r for r in group(GrowthEvent.ref) if r["key"] != "unknown"],
            "daily": [{"date": d, "visitors": v, "events": e}
                      for d, v, e in daily_rows],
        }
    finally:
        db.close()


def compare(days: int = 1) -> dict:
    """This window against the one before it, for the dashboard's deltas."""
    now = summary(days)
    db = SessionLocal()
    try:
        end = datetime.now(timezone.utc) - timedelta(days=days)
        start = end - timedelta(days=max(0, days - 1))
        s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        prev_visitors = (
            db.query(func.count(func.distinct(GrowthEvent.visitor_hash)))
            .filter(GrowthEvent.event_date >= s, GrowthEvent.event_date <= e)
            .scalar() or 0
        )
    finally:
        db.close()

    current = now["totals"]["visitors"]
    delta = None
    if prev_visitors:
        delta = round((current - prev_visitors) / prev_visitors, 4)
    return {"current": current, "previous": prev_visitors, "change": delta}
