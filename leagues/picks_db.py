"""
Persistence + settlement for published category picks.

The rollover chain has always been stored and settled, which is why the
Results page could only ever show rollover days. Category picks (banker,
2 odds, 5 odds, 10 odds, over 1.5) were generated fresh on every request and
never written anywhere, so once a match finished there was no record that we
had ever tipped it — nothing to settle, nothing to show, no track record.

Every published slip is now archived on the day it is generated and settled
against real scores afterwards, so the site can show an honest history for
every category rather than for one of them.

Falls back to no-ops when the database is unreachable so local dev still runs.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from database import Base, SessionLocal

logger = logging.getLogger(__name__)


class PublishedSlip(Base):
    """One published accumulator for one category on one date."""
    __tablename__ = "published_slips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), nullable=False, index=True)      # YYYY-MM-DD
    category = Column(String(20), nullable=False, index=True)  # banker | 2_odds | ...
    picks = Column(Text, nullable=False)                       # JSON list
    total_odds = Column(Float, nullable=False)
    hit_probability = Column(Float, default=0.0)
    status = Column(String(20), default="pending")             # pending|won|lost|void
    settled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_table() -> bool:
    try:
        from database import engine
        Base.metadata.create_all(bind=engine, tables=[PublishedSlip.__table__])
        return True
    except Exception as e:
        logger.warning(f"Could not ensure published_slips table: {e}")
        return False


def archive_slip(date: str, category: str, games: list[dict],
                 total_odds: float, hit_probability: float) -> bool:
    """Record a published slip. Idempotent per (date, category).

    Re-published slips overwrite only while still pending — once a slip is
    settled its record is frozen, so the track record cannot be rewritten by
    a later regeneration.
    """
    if not games:
        return False
    try:
        db = SessionLocal()
        try:
            existing = (
                db.query(PublishedSlip)
                .filter(PublishedSlip.date == date, PublishedSlip.category == category)
                .first()
            )
            payload = json.dumps([
                {
                    "match_id": g.get("match_id"),
                    "home_team": g.get("home_team"),
                    "away_team": g.get("away_team"),
                    "league": g.get("league"),
                    "commence_time": g.get("kickoff") or g.get("date"),
                    "prediction": g.get("prediction"),
                    "market": g.get("market"),
                    "market_group": g.get("prediction_type"),
                    "odds": g.get("odds"),
                    "odds_are_real": g.get("odds_are_real", False),
                    "confidence": g.get("confidence"),
                    "home_team_logo": g.get("home_team_logo"),
                    "away_team_logo": g.get("away_team_logo"),
                    "status": "pending",
                }
                for g in games
            ])

            if existing:
                if existing.status != "pending":
                    return True  # already settled — leave history intact
                existing.picks = payload
                existing.total_odds = total_odds
                existing.hit_probability = hit_probability
            else:
                db.add(PublishedSlip(
                    date=date, category=category, picks=payload,
                    total_odds=total_odds, hit_probability=hit_probability,
                    status="pending",
                ))
            db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"archive_slip failed ({date}/{category}): {e}")
        return False


def get_history(limit_days: int = 30, category: Optional[str] = None) -> list[dict]:
    """Published slips, newest first."""
    try:
        db = SessionLocal()
        try:
            q = db.query(PublishedSlip)
            if category:
                q = q.filter(PublishedSlip.category == category)
            rows = q.order_by(PublishedSlip.date.desc(), PublishedSlip.id.desc()).limit(limit_days * 6).all()
            return [
                {
                    "date": r.date,
                    "category": r.category,
                    "status": r.status,
                    "total_odds": r.total_odds,
                    "hit_probability": r.hit_probability,
                    "picks": json.loads(r.picks or "[]"),
                    "settled_at": r.settled_at.isoformat() if r.settled_at else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"get_history failed: {e}")
        return []


def pending_slips(before_date: str) -> list[Any]:
    """Unsettled slips whose date is on or before `before_date`."""
    try:
        db = SessionLocal()
        try:
            return (
                db.query(PublishedSlip)
                .filter(PublishedSlip.status == "pending", PublishedSlip.date <= before_date)
                .all()
            )
        finally:
            db.close()
    except Exception:
        return []


def settle_slip(slip_id: int, pick_results: list[str]) -> Optional[str]:
    """Apply per-leg outcomes and set the slip status.

    A slip wins only when every leg wins. It is lost as soon as any leg loses,
    even while other legs are unresolved — a lost leg cannot be recovered.
    """
    try:
        db = SessionLocal()
        try:
            slip = db.query(PublishedSlip).filter(PublishedSlip.id == slip_id).first()
            if not slip:
                return None
            picks = json.loads(slip.picks or "[]")
            for pick, outcome in zip(picks, pick_results):
                pick["status"] = outcome

            if any(o == "lost" for o in pick_results):
                status = "lost"
            elif all(o in ("won", "void") for o in pick_results) and pick_results:
                status = "won"
            else:
                status = "pending"

            slip.picks = json.dumps(picks)
            if status != "pending":
                slip.status = status
                slip.settled_at = datetime.utcnow()
            db.commit()
            return status
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"settle_slip failed: {e}")
        return None


def performance_summary(limit_days: int = 90) -> dict:
    """Aggregate win rate per category, plus profit on level 1-unit stakes."""
    history = get_history(limit_days=limit_days)
    by_cat: dict[str, dict] = {}
    for slip in history:
        if slip["status"] not in ("won", "lost"):
            continue
        c = by_cat.setdefault(slip["category"], {"won": 0, "lost": 0, "staked": 0.0, "returned": 0.0})
        if slip["status"] == "won":
            c["won"] += 1
            c["returned"] += slip["total_odds"]
        else:
            c["lost"] += 1
        c["staked"] += 1.0

    for c in by_cat.values():
        settled = c["won"] + c["lost"]
        c["settled"] = settled
        c["win_rate"] = round(c["won"] / settled, 4) if settled else 0.0
        c["profit"] = round(c["returned"] - c["staked"], 2)
        c["roi"] = round((c["returned"] - c["staked"]) / c["staked"], 4) if c["staked"] else 0.0
    return by_cat
