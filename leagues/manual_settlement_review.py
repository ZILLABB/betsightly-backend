"""Read-only pending manual result queue; never changes betting records."""
import json
from collections import Counter
from datetime import datetime, timezone
from sqlalchemy import text


def _kickoff(game):
    try:
        dt = datetime.fromisoformat(str(game.get("kickoff") or
                                     game.get("commence_time") or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def build_review_queue(rows, *, limit=250, now=None):
    current = now or datetime.now(timezone.utc)
    items = []
    for day, tier, raw in rows:
        slip = json.loads(raw) if isinstance(raw, str) else raw
        for leg in slip.get("games") or []:
            if leg.get("status", "pending") != "pending":
                continue
            when = _kickoff(leg)
            age = round((current - when).total_seconds() / 3600, 1) if when else None
            country = (leg.get("competition_country") or
                       leg.get("sportybet_country") or
                       leg.get("sportybet_category"))
            sources = leg.get("settlement_source_candidates") or []
            kind = ("missing_kickoff" if not when else
                    "country_unknown" if not country else
                    "source_recheck" if sources else "source_unsupported")
            items.append({
                "date": str(day), "tier": tier,
                "event_id": leg.get("sportybet_event_id"),
                "home": leg.get("home_team"), "away": leg.get("away_team"),
                "kickoff": when.isoformat() if when else None,
                "league": leg.get("league"), "league_slug": leg.get("league_slug"),
                "country": country,
                "country_basis": ("registry" if leg.get("competition_country") else
                                  "bookmaker" if country else "unknown"),
                "tournament_id": leg.get("sportybet_tournament_id"),
                "category_id": leg.get("sportybet_category_id"),
                "source_candidates": sources,
                "pending_reason": leg.get("settlement_pending_reason") or "FINAL_SCORE_UNVERIFIED",
                "review_category": kind, "age_hours": age,
                "overdue_48h": bool(age is not None and age >= 48),
            })
    items.sort(key=lambda r: (not r["overdue_48h"], r["kickoff"] or "", r["event_id"] or ""))
    size = max(1, min(1000, int(limit)))
    return {
        "status": "ok", "read_only": True,
        "total_pending_legs": len(items),
        "overdue_48h": sum(r["overdue_48h"] for r in items),
        "unique_events": len(set(r["event_id"] for r in items if r["event_id"])),
        "review_categories": dict(Counter(r["review_category"] for r in items)),
        "returned": min(size, len(items)), "legs": items[:size],
    }


def manual_settlement_review(*, limit=250):
    from database import engine
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT publish_date,tier,detail FROM editorial_tier_slips "
            "ORDER BY publish_date DESC,tier")).all()
    return build_review_queue(rows, limit=limit)
