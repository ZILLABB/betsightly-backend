"""First-party, privacy-safe product and operations analytics for BetSightly."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import text

from database import SessionLocal, engine
from growth.analytics_enrichment import (
    PRODUCT_SOURCES, SYSTEM_EVENT, SYSTEM_EVENT_TYPES, USER_EVENT,
    USER_EVENT_TYPES, classify_event, device_info, product_source,
    traffic_source,
)
from growth.models import GrowthEvent, ensure_tables

logger = logging.getLogger(__name__)

ALIASES = {
    "code_generated": "booking_code_generated",
    "code_validated": "booking_code_validated",
    "code_displayed": "booking_code_viewed",
    "code_copied": "booking_code_copied",
    "telegram_click": "telegram_join_clicked",
    "sportybet_open_clicked": "sportybet_opened",
    "partial_booking_created": "partial_booking_used",
}
EVENT_TYPES = USER_EVENT_TYPES | SYSTEM_EVENT_TYPES | set(ALIASES)

_cache: dict = {"key": None, "at": 0.0, "value": None}
CACHE_SECONDS = 60


def _hash(raw: str) -> str:
    salt = os.getenv("SECRET_KEY", "betsightly")
    return hashlib.sha256(f"{raw}|{salt}".encode()).hexdigest()[:32]


def _visitor_hash(ip: str, user_agent: str, date: str,
                  visitor_id: Optional[str] = None) -> str:
    if visitor_id:
        return _hash(f"visitor|{visitor_id[:128]}")
    # Compatibility for browsers that block localStorage. It is intentionally
    # daily-scoped, so it cannot become a long-lived IP-based identity.
    return _hash(f"legacy|{ip}|{user_agent}|{date}")


def _bounded_int(value, maximum: int) -> Optional[int]:
    try:
        number = int(value)
        return number if 0 < number <= maximum else None
    except (TypeError, ValueError):
        return None


def record(*, event_type: str, path: Optional[str] = None,
           source: Optional[str] = None, medium: Optional[str] = None,
           campaign: Optional[str] = None, content_tag: Optional[str] = None,
           utm_term: Optional[str] = None, ref: Optional[str] = None,
           referrer: Optional[str] = None, ip: str = "", user_agent: str = "",
           visitor_id: Optional[str] = None, session_id: Optional[str] = None,
           event_id: Optional[str] = None, tier: Optional[str] = None,
           target_odds: Optional[float] = None,
           booking_status: Optional[str] = None, leg_count: Optional[int] = None,
           actual_odds: Optional[float] = None,
           country_code: Optional[str] = None, region: Optional[str] = None,
           city: Optional[str] = None, timezone_name: Optional[str] = None,
           browser: Optional[str] = None, screen_width=None, screen_height=None,
           booking_id: Optional[str] = None, product_area: Optional[str] = None,
           geo_source: Optional[str] = None,
           metadata: Optional[dict] = None) -> bool:
    """Record one event; duplicate event IDs are accepted as successful no-ops."""
    try:
        ensure_tables()
        canonical = ALIASES.get(event_type, event_type)
        if event_type not in EVENT_TYPES and canonical not in EVENT_TYPES:
            return False
        event_class = classify_event(canonical)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        is_user = event_class == USER_EVENT
        vhash = _visitor_hash(ip, user_agent, today, visitor_id) if is_user else None
        shash = _hash(f"session|{session_id}") if is_user and session_id else None
        event_key = _hash(f"event|{event_id}") if event_id else None
        acquisition, normalized_medium, ref_host = traffic_source(
            source, medium, referrer)
        detected = device_info(user_agent) if is_user else {
            "device_type": None, "operating_system": None, "browser": None}
        area = product_source(product_area, content_tag, path, tier)
        country_code = (country_code or "").strip().upper()
        if len(country_code) != 2 or not country_code.isalpha():
            country_code = None

        db = SessionLocal()
        try:
            if event_key and db.query(GrowthEvent.id).filter(
                    GrowthEvent.event_key == event_key).first():
                return True
            seen = bool(vhash and db.query(GrowthEvent.id).filter(
                GrowthEvent.visitor_hash == vhash).first())
            details = dict(metadata or {})
            if geo_source:
                details["geo_source"] = geo_source
            db.add(GrowthEvent(
                event_date=today, event_type=canonical, event_class=event_class,
                path=(path or "")[:256] or None,
                source=(acquisition or "Unknown")[:64],
                medium=(normalized_medium or "")[:64] or None,
                campaign=(campaign or "")[:64] or None,
                content_tag=(content_tag or "")[:64] or None,
                utm_term=(utm_term or "")[:64] or None,
                ref=(ref or "")[:64] or None,
                visitor_hash=vhash, session_hash=shash, event_key=event_key,
                is_new_visitor=is_user and not seen,
                referrer_host=(ref_host or "")[:128] or None,
                tier=(tier or "")[:32] or None,
                target_odds=float(target_odds) if target_odds is not None else None,
                booking_status=(booking_status or "")[:32] or None,
                leg_count=_bounded_int(leg_count, 100),
                actual_odds=float(actual_odds) if actual_odds is not None else None,
                country=country_code, country_code=country_code,
                region=(region or "")[:96] or None,
                city=(city or "")[:96] or None,
                timezone=(timezone_name or "")[:64] or None,
                device_category=detected["device_type"],
                os_family=detected["operating_system"],
                browser_family=(browser or detected["browser"] or "")[:32] or None,
                screen_width=_bounded_int(screen_width, 20000),
                screen_height=_bounded_int(screen_height, 20000),
                booking_id=(booking_id or "")[:64] or None,
                product_source=area if area in PRODUCT_SOURCES else "OTHER",
                metadata_json=json.dumps(details, separators=(",", ":"))[:2000],
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


def _canonical(event: GrowthEvent) -> str:
    return ALIASES.get(event.event_type, event.event_type)


def _is_user(event: GrowthEvent) -> bool:
    if event.event_class:
        return event.event_class == USER_EVENT
    return classify_event(_canonical(event)) == USER_EVENT


def _event_time(event: GrowthEvent):
    return (event.created_at or datetime.min, event.id or 0)


def _entity(event: GrowthEvent) -> str:
    return (event.booking_id or
            f"{event.visitor_hash}|{event.product_source or event.content_tag}|"
            f"{event.tier}|{event.event_date}")


def _area(event: GrowthEvent) -> str:
    return product_source(event.product_source, event.content_tag,
                          event.path, event.tier)


def _booking_metrics(start: str, end: str) -> dict:
    empty = {"attempts": 0, "full": 0, "rebuilt": 0, "partial": 0,
             "unavailable": 0, "failed": 0, "validation_failed": 0,
             "no_code_rate": None, "success_rate": None,
             "validation_success_rate": None, "by_tier": [], "failures": []}
    try:
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT publish_date,tier,status,booking_status,"
                "actual_sportybet_odds,detail FROM tier_bookings "
                "WHERE publish_date>=:s AND publish_date<=:e"),
                {"s": start, "e": end}).fetchall()
        by_tier, failures, odds = defaultdict(Counter), Counter(), defaultdict(list)
        for _, tier, _, booking_status, actual, detail in rows:
            tier = tier or "unknown"
            bucket = by_tier[tier]
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
                failures[(str(reason)[:80], tier)] += 1
            if actual:
                odds[tier].append(float(actual))
        out, total = dict(empty), len(rows)
        out["attempts"] = total
        for key in ("full", "rebuilt", "partial", "unavailable", "failed", "validation_failed"):
            out[key] = sum(values[key] for values in by_tier.values())
        successful = out["full"] + out["rebuilt"] + out["partial"]
        validated = successful + out["validation_failed"]
        out["success_rate"] = round(successful / total, 4) if total else None
        out["no_code_rate"] = round((total - successful) / total, 4) if total else None
        out["validation_success_rate"] = round(successful / validated, 4) if validated else None
        out["by_tier"] = [{"tier": tier, **dict(values),
                           "avg_actual_odds": (round(sum(odds[tier]) / len(odds[tier]), 2)
                                               if odds[tier] else None)}
                          for tier, values in sorted(by_tier.items())]
        out["failures"] = [{"reason": reason, "tier": tier, "count": count}
                           for (reason, tier), count in failures.most_common(12)]
        return out
    except Exception as exc:
        logger.debug(f"booking analytics unavailable: {exc}")
        return empty


def _progression_funnel(events: list[GrowthEvent],
                        stages: list[tuple[str, Callable[[GrowthEvent], bool]]]) -> list[dict]:
    by_visitor = defaultdict(list)
    for event in events:
        if event.visitor_hash:
            by_visitor[event.visitor_hash].append(event)
    progressed = {visitor: None for visitor in by_visitor}
    output = []
    previous = None
    for label, predicate in stages:
        next_progressed = {}
        for visitor, after in progressed.items():
            matches = [e for e in by_visitor[visitor]
                       if predicate(e) and (after is None or _event_time(e) >= after)]
            if matches:
                next_progressed[visitor] = min(_event_time(e) for e in matches)
        count = len(next_progressed)
        conversion = count / previous if previous else (1.0 if count and previous is None else None)
        output.append({"label": label, "count": count,
                       "conversion": round(conversion, 4) if conversion is not None else None,
                       "dropoff": round(1 - conversion, 4) if conversion is not None else None})
        progressed = next_progressed
        previous = count
    return output


def summary(days: int = 1, start: Optional[str] = None,
            end: Optional[str] = None) -> dict:
    """One cached command-center payload with user and system metrics separated."""
    start, end = _dates(days, start, end)
    key = (start, end)
    if _cache["key"] == key and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    ensure_tables()
    db = SessionLocal()
    try:
        events = db.query(GrowthEvent).filter(
            GrowthEvent.event_date >= start, GrowthEvent.event_date <= end).all()
        user_events = [event for event in events if _is_user(event)]
        system_events = [event for event in events if not _is_user(event)]
        visitor_ids = {event.visitor_hash for event in user_events if event.visitor_hash}
        identity_events = (db.query(GrowthEvent).filter(
            GrowthEvent.visitor_hash.in_(visitor_ids)).all() if visitor_ids else [])
        identity_events = [event for event in identity_events if _is_user(event)]
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=29)).strftime("%Y-%m-%d")
        recent_events = db.query(GrowthEvent).filter(
            GrowthEvent.event_date >= recent_cutoff).all()
        recent_user_events = [event for event in recent_events if _is_user(event)]
    finally:
        db.close()

    counts = Counter(_canonical(event) for event in user_events)
    system_counts = Counter(_canonical(event) for event in system_events)
    visitor_dates = defaultdict(set)
    first_dates = {}
    for event in identity_events:
        if not event.visitor_hash:
            continue
        visitor_dates[event.visitor_hash].add(event.event_date)
        first_dates[event.visitor_hash] = min(first_dates.get(event.visitor_hash, event.event_date),
                                              event.event_date)
    new = {visitor for visitor in visitor_ids if first_dates.get(visitor, start) >= start}
    returning = {visitor for visitor in visitor_ids
                 if first_dates.get(visitor, start) < start or len(visitor_dates[visitor]) > 1}

    active_users = {}
    now = datetime.now(timezone.utc)
    for label, window in (("dau", 1), ("wau", 7), ("mau", 30)):
        cutoff = (now - timedelta(days=window - 1)).strftime("%Y-%m-%d")
        active_users[label] = len({event.visitor_hash for event in recent_user_events
                                   if event.event_date >= cutoff and event.visitor_hash})

    valid_views = [event for event in user_events if _canonical(event) == "booking_code_viewed"]
    copy_events = [event for event in user_events if _canonical(event) == "booking_code_copied"]
    valid_entities = {_entity(event) for event in valid_views}
    copied_entities = {_entity(event) for event in copy_events}
    viewed_visitors = {event.visitor_hash for event in valid_views if event.visitor_hash}
    copied_visitors = {event.visitor_hash for event in copy_events if event.visitor_hash}
    converted_entities = copied_entities & valid_entities
    converted_visitors = copied_visitors & viewed_visitors

    def dimension(name: str):
        grouped = defaultdict(list)
        for event in user_events:
            value = ((event.country_code or event.country) if name == "country_code"
                     else getattr(event, name))
            grouped[value or "unknown"].append(event)
        rows = []
        for label, items in grouped.items():
            visitors = {event.visitor_hash for event in items if event.visitor_hash}
            sessions = {event.session_hash for event in items if event.session_hash}
            prediction_viewers = {event.visitor_hash for event in items
                                  if _canonical(event) == "prediction_viewed" and event.visitor_hash}
            builder_users = {event.visitor_hash for event in items
                             if _canonical(event) == "builder_opened" and event.visitor_hash}
            item_viewers = {event.visitor_hash for event in items
                            if _canonical(event) == "booking_code_viewed" and event.visitor_hash}
            item_copiers = {event.visitor_hash for event in items
                            if _canonical(event) == "booking_code_copied" and event.visitor_hash}
            item_opens = {event.visitor_hash for event in items
                          if _canonical(event) == "sportybet_opened" and event.visitor_hash}
            rows.append({
                "key": label, "count": len(items), "visitors": len(visitors),
                "returning": len(visitors & returning), "sessions": len(sessions),
                "prediction_viewers": len(prediction_viewers),
                "prediction_views": sum(_canonical(e) == "prediction_viewed" for e in items),
                "builders": len(builder_users), "code_copiers": len(item_copiers),
                "copy_actions": sum(_canonical(e) == "booking_code_copied" for e in items),
                "sportybet_opens": len(item_opens),
                "prediction_view_rate": round(len(prediction_viewers) / len(visitors), 4) if visitors else None,
                "builder_usage_rate": round(len(builder_users) / len(visitors), 4) if visitors else None,
                "copy_conversion": round(len(item_copiers & item_viewers) / len(item_viewers), 4)
                                   if item_viewers else None,
                "sportybet_open_rate": round(len(item_opens & item_viewers) / len(item_viewers), 4)
                                       if item_viewers else None,
                "return_rate": round(len(visitors & returning) / len(visitors), 4) if visitors else None,
            })
        return sorted(rows, key=lambda row: row["visitors"], reverse=True)[:25]

    prediction_sources = {"PREDICTIONS", "BANKER", "TWO_ODDS", "FIVE_ODDS",
                          "TEN_ODDS", "OVER_1_5", "FALLBACK"}
    funnels = {
        "prediction": _progression_funnel(user_events, [
            ("Visitors", lambda e: True),
            ("Predictions viewed", lambda e: _canonical(e) == "prediction_viewed"),
            ("Valid code displayed", lambda e: _canonical(e) == "booking_code_viewed"
             and _area(e) in prediction_sources),
            ("Code copied", lambda e: _canonical(e) == "booking_code_copied"
             and _area(e) in prediction_sources),
            ("SportyBet opened", lambda e: _canonical(e) == "sportybet_opened"
             and _area(e) in prediction_sources),
        ]),
        "builder": _progression_funnel(user_events, [
            ("Builder opened", lambda e: _canonical(e) == "builder_opened"),
            ("Target selected", lambda e: _canonical(e) == "builder_target_selected"),
            ("Slip generated", lambda e: _canonical(e) == "builder_generated"),
            ("Valid code displayed", lambda e: _canonical(e) == "booking_code_viewed"
             and _area(e) == "BUILD_SLIP"),
            ("Code copied", lambda e: _canonical(e) == "booking_code_copied"
             and _area(e) == "BUILD_SLIP"),
            ("SportyBet opened", lambda e: _canonical(e) == "sportybet_opened"
             and _area(e) == "BUILD_SLIP"),
        ]),
        "rollover": _progression_funnel(user_events, [
            ("Rollover viewed", lambda e: _canonical(e) == "rollover_viewed"),
            ("Valid code displayed", lambda e: _canonical(e) == "booking_code_viewed"
             and _area(e) == "ROLLOVER"),
            ("Code copied", lambda e: _canonical(e) == "booking_code_copied"
             and _area(e) == "ROLLOVER"),
            ("SportyBet opened", lambda e: _canonical(e) == "sportybet_opened"
             and _area(e) == "ROLLOVER"),
        ]),
    }

    daily = []
    for date in sorted({event.event_date for event in user_events}):
        day = [event for event in user_events if event.event_date == date]
        daily.append({"date": date,
                      "visitors": len({e.visitor_hash for e in day if e.visitor_hash}),
                      "sessions": len({e.session_hash for e in day if e.session_hash}),
                      "events": len(day),
                      "builds": sum(_canonical(e) == "builder_generated" for e in day),
                      "codes_displayed": len({_entity(e) for e in day
                                              if _canonical(e) == "booking_code_viewed"}),
                      "copy_actions": sum(_canonical(e) == "booking_code_copied" for e in day)})

    retention, today = {}, datetime.now(timezone.utc).date()
    for offset in (1, 3, 7, 14, 30):
        eligible = matched = 0
        for visitor in new:
            first = datetime.strptime(first_dates.get(visitor, start), "%Y-%m-%d").date()
            if first + timedelta(days=offset) > today:
                continue
            eligible += 1
            matched += (first + timedelta(days=offset)).isoformat() in visitor_dates[visitor]
        retention[f"d{offset}"] = {"rate": round(matched / eligible, 4) if eligible else None,
                                     "returned": matched, "eligible": eligible}

    booking = _booking_metrics(start, end)
    builder_events = [event for event in user_events if _area(event) == "BUILD_SLIP"]
    builder_generators = {e.visitor_hash for e in builder_events
                          if _canonical(e) == "builder_generated" and e.visitor_hash}
    builder_viewers = {e.visitor_hash for e in builder_events
                       if _canonical(e) == "booking_code_viewed" and e.visitor_hash}
    targets = Counter(str(int(event.target_odds)) for event in builder_events
                      if event.target_odds and _canonical(event) == "builder_target_selected")
    generated = [event for event in builder_events if _canonical(event) == "builder_generated"]
    builder = {
        "targets": [{"key": name, "count": count} for name, count in targets.most_common()],
        "most_popular_target": targets.most_common(1)[0][0] if targets else None,
        "generated": len(generated), "bookable": len(builder_viewers),
        "success_rate": round(len(builder_viewers & builder_generators) / len(builder_generators), 4)
                        if builder_generators else None,
        "average_legs": round(sum(e.leg_count or 0 for e in generated) / len(generated), 1)
                        if generated else None,
        "average_actual_odds": (round(sum(e.actual_odds for e in generated if e.actual_odds) /
                                      len([e for e in generated if e.actual_odds]), 2)
                                if any(e.actual_odds for e in generated) else None),
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

    def coverage(attribute: str, unknown=(None, "", "unknown", "Unknown", "Other")):
        if not user_events:
            return None
        known = sum(getattr(event, attribute, None) not in unknown for event in user_events)
        return round(known / len(user_events), 4)

    analytics_quality = {
        "geo_coverage": (round(sum(bool(e.country_code or e.country) for e in user_events) /
                               len(user_events), 4) if user_events else None),
        "device_coverage": coverage("device_category"),
        "os_coverage": coverage("os_family"),
        "browser_coverage": coverage("browser_family"),
        "referrer_attribution": (round(sum((e.source or "").lower() not in
                                           {"", "unknown", "direct"} for e in user_events) /
                                         len(user_events), 4) if user_events else None),
        "stable_visitor_coverage": (round(sum(bool(e.visitor_hash and e.session_hash)
                                              for e in user_events) / len(user_events), 4)
                                    if user_events else None),
    }

    totals = {
        "events": len(user_events), "system_events": len(system_events),
        "pageviews": counts["pageview"], "visitors": len(visitor_ids),
        "sessions": len({e.session_hash for e in user_events if e.session_hash}),
        "new_visitors": len(new), "returning_visitors": len(returning),
        "predictions_viewed": counts["prediction_viewed"],
        "prediction_viewers": len({e.visitor_hash for e in user_events
                                    if _canonical(e) == "prediction_viewed" and e.visitor_hash}),
        "rollover_views": counts["rollover_viewed"],
        "rollover_users": len({e.visitor_hash for e in user_events
                                if _canonical(e) == "rollover_viewed" and e.visitor_hash}),
        "builder_opened": counts["builder_opened"],
        "builder_users": len({e.visitor_hash for e in user_events
                              if _canonical(e) == "builder_opened" and e.visitor_hash}),
        "slip_builds": counts["builder_generated"],
        "slip_generators": len(builder_generators),
        "valid_codes_displayed": len(valid_entities),
        "valid_code_viewers": len(viewed_visitors),
        "total_copy_actions": len(copy_events),
        "unique_code_copiers": len(copied_visitors),
        "unique_codes_copied": len(copied_entities),
        "sportybet_opened": counts["sportybet_opened"],
        "sportybet_openers": len({e.visitor_hash for e in user_events
                                  if _canonical(e) == "sportybet_opened" and e.visitor_hash}),
        "code_copy_rate": (round(len(converted_entities) / len(valid_entities), 4)
                           if valid_entities else None),
        "user_copy_rate": (round(len(converted_visitors) / len(viewed_visitors), 4)
                           if viewed_visitors else None),
        # Compatibility names now intentionally refer only to system events.
        "codes_generated": system_counts["booking_code_generated"],
        "codes_validated": system_counts["booking_code_validated"],
        "codes_copied": len(copy_events),
    }
    # PostHog owns human/product analytics. During the fixed dual-validation
    # window the legacy values stay alongside it so discrepancies are visible.
    try:
        from growth.posthog_adapter import summary as posthog_summary
        posthog = posthog_summary(start, end)
    except Exception as exc:
        posthog = {"data": {}, "meta": {"source": "posthog", "status": "unavailable",
                   "as_of": None, "freshness_seconds": None,
                   "reason": f"adapter_failed:{type(exc).__name__}"}}
    legacy_comparison = {"totals": dict(totals), "analytics_quality": analytics_quality}
    provider_data = posthog.get("data") or {}
    if provider_data.get("totals"):
        totals.update(provider_data["totals"])
    try:
        from leagues.builder_runs import summary as builder_run_summary
        builder_backend = builder_run_summary(start, end)
    except Exception as exc:
        builder_backend = {"requests": 0, "tickets_produced": 0,
                           "ticket_rate": None, "cache_hits": 0,
                           "by_target": [], "failures": [],
                           "status": f"unavailable:{type(exc).__name__}"}
    now_iso = datetime.now(timezone.utc).isoformat()
    from growth.metric_contracts import conversion, retention as retention_contract, source_meta
    metric_contracts = {
        "code_copy_rate": conversion(totals.get("unique_code_copiers", 0),
                                     totals.get("valid_code_viewers", 0)),
        "sportybet_open_rate": conversion(totals.get("sportybet_openers", 0),
                                           totals.get("valid_code_viewers", 0)),
        "builder_ticket_rate": conversion(builder_backend.get("tickets_produced", 0),
                                           builder_backend.get("requests", 0)),
    }
    provider_retention = provider_data.get("retention") or retention
    for label, item in provider_retention.items():
        metric_contracts[f"retention_{label}"] = retention_contract(
            item.get("returned", 0), item.get("eligible", 0))
    prediction_return = provider_data.get("prediction_day_return") or {}
    metric_contracts["prediction_day_return"] = retention_contract(
        prediction_return.get("returned", 0), prediction_return.get("eligible", 0))
    overlap = ("pageviews", "prediction_viewers", "builder_users", "valid_code_viewers",
               "unique_code_copiers", "sportybet_openers")
    legacy_comparison["difference"] = {
        name: ((totals.get(name, 0) - legacy_comparison["totals"].get(name, 0))
               if provider_data.get("totals") else None) for name in overlap}
    sources = {
        "human_analytics": posthog["meta"],
        "backend_facts": source_meta("betsightly_db", now_iso),
        "sportybet_catalogue": source_meta(
            "sportybet", sportybet.get("fetched_at") or sportybet.get("as_of") or now_iso,
            ("unavailable" if not sportybet else "stale"
             if sportybet.get("error") or (sportybet.get("cache_age_hours") or 0) > 6
             else "fresh"),
            int((sportybet.get("cache_age_hours") or 0) * 3600) if sportybet else None),
    }
    section_meta = {
        "audience": sources["human_analytics"],
        "product": sources["human_analytics"],
        "predictions": sources["backend_facts"],
        "sportybet": sources["backend_facts"],
        "operations": sources["backend_facts"],
    }
    payload = {
        "window_days": (datetime.strptime(end, "%Y-%m-%d") -
                        datetime.strptime(start, "%Y-%m-%d")).days + 1,
        "start": start, "end": end, "totals": totals,
        "funnel": (provider_data.get("funnels") or funnels)["prediction"],
        "funnels": provider_data.get("funnels") or funnels,
        "retention": provider_data.get("retention") or retention,
        "prediction_day_return": provider_data.get("prediction_day_return") or {},
        "daily": provider_data.get("daily") or daily,
        "active_users": provider_data.get("active_users") or active_users,
        "builder": builder, "builder_backend": builder_backend,
        "analytics_quality": analytics_quality,
        "system_event_counts": dict(system_counts),
        "by_source": provider_data.get("by_source") or dimension("source"),
        "by_campaign": provider_data.get("by_campaign") or dimension("campaign"),
        "by_path": provider_data.get("by_path") or dimension("path"),
        "by_country": provider_data.get("by_country") or dimension("country_code"),
        "by_device": provider_data.get("by_device") or dimension("device_category"),
        "by_os": provider_data.get("by_os") or dimension("os_family"),
        "by_browser": provider_data.get("by_browser") or dimension("browser_family"),
        "by_region": provider_data.get("by_region") or dimension("region"),
        "by_tier": dimension("tier"),
        "by_product_source": dimension("product_source"),
        "booking": booking, "sportybet": sportybet,
        "prediction_performance": prediction_performance, "operations": operations,
        "analytics_provider": posthog["meta"], "sources": sources,
        "section_meta": section_meta, "metric_contracts": metric_contracts,
        "legacy_comparison": legacy_comparison,
        "analytics_health": {
            "provider": posthog["meta"], "quality": analytics_quality,
            "schema_validation_errors": totals.get("schema_validation_errors"),
            "dual_write_comparison": legacy_comparison.get("difference"),
            "vercel_pageview_variance": {"status": "unavailable",
                                         "reason": "Vercel aggregate API is not configured"},
            "dual_write_until": os.getenv("ANALYTICS_DUAL_WRITE_UNTIL",
                                           "2026-09-17T23:59:59Z"),
            "migration_complete": False,
        },
        "limitations": [
            "Historical events are not fabricated; missing enrichment remains unknown.",
            "Anonymous browser identity can be cleared and does not link devices.",
            "Code copied and SportyBet opened do not prove a bet was placed.",
        ],
    }
    _cache.update({"key": key, "at": time.time(), "value": payload})
    return payload


def compare(days: int = 1, start: Optional[str] = None,
            end: Optional[str] = None) -> dict:
    current = summary(days, start, end)
    first = datetime.strptime(current["start"], "%Y-%m-%d")
    last = datetime.strptime(current["end"], "%Y-%m-%d")
    width = (last - first).days + 1
    previous_end = first - timedelta(days=1)
    previous_start = previous_end - timedelta(days=width - 1)
    previous = summary(width, previous_start.strftime("%Y-%m-%d"),
                       previous_end.strftime("%Y-%m-%d"))
    booking_keys = ("attempts", "full", "rebuilt", "partial", "unavailable",
                    "failed", "validation_failed", "success_rate", "no_code_rate",
                    "validation_success_rate")
    current_values = {**current["totals"],
                      **{key: current["booking"].get(key) for key in booking_keys}}
    previous_values = {**previous["totals"],
                       **{key: previous["booking"].get(key) for key in booking_keys}}
    changes = {}
    for metric, value in current_values.items():
        old = previous_values.get(metric)
        changes[metric] = (round((value - old) / old, 4)
                           if isinstance(value, (int, float)) and old else None)
    return {"current": current_values, "previous": previous_values, "changes": changes}
