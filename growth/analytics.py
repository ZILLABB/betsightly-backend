"""First-party, privacy-safe product and operations analytics for BetSightly."""

import hashlib
import json
import logging
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import func, text

from database import SessionLocal, engine
from growth.models import GrowthEvent, ensure_tables

logger = logging.getLogger(__name__)

EVENT_TYPES = {
    "pageview", "prediction_viewed", "rollover_viewed", "builder_opened",
    "builder_target_selected", "builder_generated", "builder_bookable",
    "booking_code_generated", "booking_code_validated", "booking_code_viewed",
    "booking_code_copied", "sportybet_open_clicked", "fallback_shown",
    "replacement_used", "partial_booking_created", "results_viewed",
    "telegram_join_clicked", "telegram_click", "cta_click", "registration",
    "outbound", "code_generated", "code_validated", "code_displayed",
    "code_copied", "code_regenerated", "replacement_details_opened",
}

ALIASES = {
    "code_generated": "booking_code_generated",
    "code_validated": "booking_code_validated",
    "code_displayed": "booking_code_viewed",
    "code_copied": "booking_code_copied",
    "telegram_click": "telegram_join_clicked",
}

REFERRER_SOURCES = {
    "google.": "google", "bing.": "bing", "duckduckgo.": "duckduckgo",
    "t.co": "x", "twitter.com": "x", "x.com": "x",
    "facebook.": "facebook", "fb.": "facebook", "instagram.": "instagram",
    "tiktok.": "tiktok", "youtube.": "youtube", "youtu.be": "youtube",
    "t.me": "telegram", "telegram.": "telegram", "reddit.": "reddit",
    "linkedin.": "linkedin", "wa.me": "whatsapp", "whatsapp.": "whatsapp",
}

_cache: dict = {"key": None, "at": 0.0, "value": None}
CACHE_SECONDS = 60


def _hash(raw: str) -> str:
    salt = os.getenv("SECRET_KEY", "betsightly")
    return hashlib.sha256(f"{raw}|{salt}".encode()).hexdigest()[:32]


def _visitor_hash(ip: str, user_agent: str, date: str,
                  visitor_id: Optional[str] = None) -> str:
    if visitor_id:
        return _hash(f"visitor|{visitor_id[:128]}")
    return _hash(f"legacy|{ip}|{user_agent}|{date}")


def _classify_referrer(referrer: Optional[str]):
    if not referrer:
        return None, None
    try:
        host = (urlparse(referrer).hostname or "").lower()
    except Exception:
        return None, None
    if not host:
        return None, None
    if "betsightly" in host:
        return None, host
    for needle, source in REFERRER_SOURCES.items():
        if needle in host:
            return source, host
    return "referral", host


def _device(user_agent: str) -> tuple[str, str]:
    ua = (user_agent or "").lower()
    if any(x in ua for x in ("ipad", "tablet")):
        device = "tablet"
    elif any(x in ua for x in ("mobile", "iphone", "android")):
        device = "mobile"
    else:
        device = "desktop"
    if "android" in ua:
        os_family = "Android"
    elif any(x in ua for x in ("iphone", "ipad", "ios")):
        os_family = "iOS"
    elif "windows" in ua:
        os_family = "Windows"
    elif any(x in ua for x in ("macintosh", "mac os")):
        os_family = "macOS"
    elif "linux" in ua:
        os_family = "Linux"
    else:
        os_family = "Other"
    return device, os_family


def record(*, event_type: str, path: Optional[str] = None,
           source: Optional[str] = None, medium: Optional[str] = None,
           campaign: Optional[str] = None, content_tag: Optional[str] = None,
           ref: Optional[str] = None, referrer: Optional[str] = None,
           ip: str = "", user_agent: str = "", visitor_id: Optional[str] = None,
           session_id: Optional[str] = None, event_id: Optional[str] = None,
           tier: Optional[str] = None, target_odds: Optional[float] = None,
           booking_status: Optional[str] = None, leg_count: Optional[int] = None,
           actual_odds: Optional[float] = None, country: Optional[str] = None,
           metadata: Optional[dict] = None) -> bool:
    """Record one product event; duplicate event ids are accepted as no-ops."""
    try:
        ensure_tables()
        event_type = ALIASES.get(event_type, event_type)
        if event_type not in EVENT_TYPES:
            return False
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        vhash = _visitor_hash(ip, user_agent, today, visitor_id)
        shash = _hash(f"session|{session_id}") if session_id else None
        event_key = _hash(f"event|{event_id}") if event_id else None
        ref_source, ref_host = _classify_referrer(referrer)
        source = source or ref_source or "direct"
        medium = medium or ("organic" if ref_source in ("google", "bing", "duckduckgo")
                            else ("referral" if ref_source else "none"))
        device, os_family = _device(user_agent)
        db = SessionLocal()
        try:
            if event_key and db.query(GrowthEvent.id).filter(
                    GrowthEvent.event_key == event_key).first():
                return True
            seen = db.query(GrowthEvent.id).filter(
                GrowthEvent.visitor_hash == vhash).first()
            db.add(GrowthEvent(
                event_date=today, event_type=event_type,
                path=(path or "")[:256] or None,
                source=(source or "")[:64] or None,
                medium=(medium or "")[:64] or None,
                campaign=(campaign or "")[:64] or None,
                content_tag=(content_tag or "")[:64] or None,
                ref=(ref or "")[:64] or None,
                visitor_hash=vhash, session_hash=shash, event_key=event_key,
                is_new_visitor=seen is None,
                referrer_host=(ref_host or "")[:128] or None,
                tier=(tier or "")[:32] or None,
                target_odds=float(target_odds) if target_odds is not None else None,
                booking_status=(booking_status or "")[:32] or None,
                leg_count=int(leg_count) if leg_count is not None else None,
                actual_odds=float(actual_odds) if actual_odds is not None else None,
                country=(country or "")[:8].upper() or None,
                device_category=device, os_family=os_family,
                metadata_json=json.dumps(metadata or {}, separators=(",", ":"))[:2000],
            ))
            db.commit()
            _cache["at"] = 0
            return True
        finally:
            db.close()
    except Exception as exc:
        logger.debug(f"growth analytics: record failed ({exc})")
        return False


def _dates(days: int, start: Optional[str] = None, end: Optional[str] = None):
    if start and end:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
        return start, end
    finish = datetime.now(timezone.utc)
    begin = finish - timedelta(days=max(0, days - 1))
    return begin.strftime("%Y-%m-%d"), finish.strftime("%Y-%m-%d")


def _booking_metrics(start: str, end: str) -> dict:
    empty = {"attempts": 0, "full": 0, "rebuilt": 0, "partial": 0,
             "unavailable": 0, "failed": 0, "validation_failed": 0,
             "no_code_rate": None, "success_rate": None, "by_tier": [],
             "failures": []}
    try:
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT publish_date,tier,status,booking_status,"
                "actual_sportybet_odds,detail FROM tier_bookings "
                "WHERE publish_date>=:s AND publish_date<=:e"),
                {"s": start, "e": end}).fetchall()
        by_tier, failures, odds = defaultdict(Counter), Counter(), defaultdict(list)
        for _, tier, _, booking_status, actual, detail in rows:
            bucket = by_tier[tier or "unknown"]
            bucket["generated"] += 1
            normalized = (booking_status or "UNAVAILABLE").upper()
            status_key = {"FULL": "full", "REBUILT_FULL": "rebuilt",
                          "PARTIAL": "partial", "VALIDATION_FAILED": "validation_failed",
                          "BOOKING_FAILED": "failed"}.get(normalized, "unavailable")
            bucket[status_key] += 1
            if status_key in ("unavailable", "failed", "validation_failed"):
                try:
                    reason = json.loads(detail or "{}").get("reason") or normalized
                except Exception:
                    reason = normalized
                failures[(str(reason)[:80], tier or "unknown")] += 1
            if actual:
                odds[tier].append(float(actual))
        out, total = dict(empty), len(rows)
        out["attempts"] = total
        for key in ("full", "rebuilt", "partial", "unavailable", "failed", "validation_failed"):
            out[key] = sum(v[key] for v in by_tier.values())
        success = out["full"] + out["rebuilt"] + out["partial"]
        out["success_rate"] = round(success / total, 4) if total else None
        out["no_code_rate"] = round((total - success) / total, 4) if total else None
        out["by_tier"] = [{"tier": tier, **dict(counts),
                           "avg_actual_odds": (round(sum(odds[tier]) / len(odds[tier]), 2)
                                               if odds[tier] else None)}
                          for tier, counts in sorted(by_tier.items())]
        out["failures"] = [{"reason": reason, "tier": tier, "count": count}
                           for (reason, tier), count in failures.most_common(12)]
        return out
    except Exception as exc:
        logger.debug(f"booking analytics unavailable: {exc}")
        return empty


def summary(days: int = 1, start: Optional[str] = None,
            end: Optional[str] = None) -> dict:
    """One cached command-center payload built from bounded aggregate reads."""
    start, end = _dates(days, start, end)
    key = (start, end)
    if _cache["key"] == key and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    ensure_tables()
    db = SessionLocal()
    try:
        events = db.query(GrowthEvent).filter(
            GrowthEvent.event_date >= start, GrowthEvent.event_date <= end).all()
        visitor_ids = {e.visitor_hash for e in events if e.visitor_hash}
        first_dates = {}
        if visitor_ids:
            rows = db.query(GrowthEvent.visitor_hash, func.min(GrowthEvent.event_date)).filter(
                GrowthEvent.visitor_hash.in_(visitor_ids)).group_by(GrowthEvent.visitor_hash).all()
            first_dates = dict(rows)
        active_users = {}
        today_dt = datetime.now(timezone.utc)
        for label, window in (("dau", 1), ("wau", 7), ("mau", 30)):
            cutoff = (today_dt - timedelta(days=window - 1)).strftime("%Y-%m-%d")
            active_users[label] = db.query(
                func.count(func.distinct(GrowthEvent.visitor_hash))).filter(
                    GrowthEvent.event_date >= cutoff).scalar() or 0
    finally:
        db.close()

    counts = Counter(ALIASES.get(e.event_type, e.event_type) for e in events)
    visitor_dates = defaultdict(set)
    for event in events:
        if event.visitor_hash:
            visitor_dates[event.visitor_hash].add(event.event_date)
    new = {v for v in visitor_ids if first_dates.get(v, start) >= start}
    returning = {v for v in visitor_ids
                 if first_dates.get(v, start) < start or len(visitor_dates[v]) > 1}

    def dimension(name: str):
        grouped = defaultdict(list)
        for event in events:
            grouped[getattr(event, name) or "unknown"].append(event)
        rows = []
        for label, items in grouped.items():
            visitors = {e.visitor_hash for e in items if e.visitor_hash}
            copies = sum(ALIASES.get(e.event_type, e.event_type) == "booking_code_copied" for e in items)
            generated = sum(ALIASES.get(e.event_type, e.event_type) == "booking_code_generated" for e in items)
            rows.append({"key": label, "count": len(items), "visitors": len(visitors),
                         "code_copies": copies,
                         "copy_rate": round(copies / generated, 4) if generated else None})
        return sorted(rows, key=lambda row: row["visitors"], reverse=True)[:25]

    stages = [("Visitors", None), ("Predictions viewed", "prediction_viewed"),
              ("Builder opened", "builder_opened"), ("Slip generated", "builder_generated"),
              ("Code generated", "booking_code_generated"),
              ("Code validated", "booking_code_validated"),
              ("Code copied", "booking_code_copied"),
              ("SportyBet opened", "sportybet_open_clicked")]
    funnel, previous = [], len(visitor_ids)
    for label, event_type in stages:
        value = len(visitor_ids) if event_type is None else counts[event_type]
        conversion = value / previous if previous else None
        funnel.append({"label": label, "count": value,
                       "conversion": round(conversion, 4) if conversion is not None else None,
                       "dropoff": round(1 - conversion, 4) if conversion is not None else None})
        previous = value

    daily = []
    for date in sorted({e.event_date for e in events}):
        day = [e for e in events if e.event_date == date]
        daily.append({"date": date,
                      "visitors": len({e.visitor_hash for e in day if e.visitor_hash}),
                      "events": len(day),
                      "builds": sum(ALIASES.get(e.event_type, e.event_type) == "builder_generated" for e in day),
                      "codes": sum(ALIASES.get(e.event_type, e.event_type) == "booking_code_generated" for e in day),
                      "copies": sum(ALIASES.get(e.event_type, e.event_type) == "booking_code_copied" for e in day)})

    retention, today = {}, datetime.now(timezone.utc).date()
    for offset in (1, 3, 7, 14, 30):
        eligible = matched = 0
        for visitor in new:
            first = datetime.strptime(first_dates.get(visitor, start), "%Y-%m-%d").date()
            if first + timedelta(days=offset) > today:
                continue
            eligible += 1
            matched += (first + timedelta(days=offset)).isoformat() in visitor_dates.get(visitor, set())
        retention[f"d{offset}"] = {"rate": round(matched / eligible, 4) if eligible else None,
                                     "returned": matched, "eligible": eligible}

    booking = _booking_metrics(start, end)
    builder_events = [event for event in events
                      if ALIASES.get(event.event_type, event.event_type)
                      in ("builder_target_selected", "builder_generated", "builder_bookable")]
    targets = Counter(str(int(event.target_odds)) for event in builder_events
                      if event.target_odds)
    generated = [event for event in builder_events
                 if ALIASES.get(event.event_type, event.event_type) == "builder_generated"]
    builder = {
        "targets": [{"key": key, "count": count} for key, count in targets.most_common()],
        "most_popular_target": targets.most_common(1)[0][0] if targets else None,
        "generated": len(generated),
        "bookable": counts["builder_bookable"],
        "success_rate": round(counts["builder_bookable"] / len(generated), 4) if generated else None,
        "average_legs": round(sum(e.leg_count or 0 for e in generated) / len(generated), 1) if generated else None,
        "average_actual_odds": round(sum(e.actual_odds or 0 for e in generated) /
                                     len([e for e in generated if e.actual_odds]), 2)
        if any(e.actual_odds for e in generated) else None,
        "regenerations": counts["code_regenerated"],
    }
    try:
        from leagues.sportybet import board_status
        sportybet = board_status()
    except Exception:
        sportybet = {}
    try:
        from leagues.picks_db import performance_summary
        prediction_performance = performance_summary(limit_days=max(1, days))
    except Exception:
        prediction_performance = {}
    try:
        from leagues.scheduler import last_runs
        operations = {"runs": last_runs(7)}
    except Exception:
        operations = {"runs": []}

    codes = counts["booking_code_generated"]
    payload = {
        "window_days": days, "start": start, "end": end,
        "totals": {"events": len(events), "pageviews": counts["pageview"],
                   "visitors": len(visitor_ids), "new_visitors": len(new),
                   "returning_visitors": len(returning),
                   "predictions_viewed": counts["prediction_viewed"],
                   "rollover_views": counts["rollover_viewed"],
                   "builder_opened": counts["builder_opened"],
                   "slip_builds": counts["builder_generated"],
                   "codes_generated": codes,
                   "codes_validated": counts["booking_code_validated"],
                   "codes_copied": counts["booking_code_copied"],
                   "sportybet_opened": counts["sportybet_open_clicked"],
                   "code_copy_rate": round(counts["booking_code_copied"] / codes, 4) if codes else None},
        "funnel": funnel, "retention": retention, "daily": daily,
        "active_users": active_users, "builder": builder,
        "by_source": dimension("source"), "by_campaign": dimension("campaign"),
        "by_path": dimension("path"), "by_country": dimension("country"),
        "by_device": dimension("device_category"), "by_os": dimension("os_family"),
        "by_tier": dimension("tier"), "booking": booking,
        "sportybet": sportybet, "prediction_performance": prediction_performance,
        "operations": operations,
        "limitations": ["Anonymous retention is approximate and begins when persistent browser IDs deploy.",
                        "Code copied and SportyBet opened do not prove a bet was placed.",
                        "Country is available only when the hosting edge supplies it."],
    }
    _cache.update({"key": key, "at": time.time(), "value": payload})
    return payload


def compare(days: int = 1, start: Optional[str] = None,
            end: Optional[str] = None) -> dict:
    current = summary(days, start, end)
    s = datetime.strptime(current["start"], "%Y-%m-%d")
    e = datetime.strptime(current["end"], "%Y-%m-%d")
    width = (e - s).days + 1
    previous_end = s - timedelta(days=1)
    previous_start = previous_end - timedelta(days=width - 1)
    previous = summary(width, previous_start.strftime("%Y-%m-%d"), previous_end.strftime("%Y-%m-%d"))
    booking_keys = ("attempts", "full", "rebuilt", "partial", "unavailable",
                    "failed", "validation_failed", "success_rate", "no_code_rate")
    current_values = {**current["totals"],
                      **{key: current["booking"].get(key) for key in booking_keys}}
    previous_values = {**previous["totals"],
                       **{key: previous["booking"].get(key) for key in booking_keys}}
    changes = {}
    for metric, value in current_values.items():
        old = previous_values.get(metric)
        changes[metric] = (round((value - old) / old, 4)
                           if isinstance(value, (int, float)) and old else None)
    return {"current": current_values, "previous": previous_values,
            "changes": changes}
