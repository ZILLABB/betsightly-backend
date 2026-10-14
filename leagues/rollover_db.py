"""
PostgreSQL persistence for the rollover chain.

The chain previously lived in worldcup/data/wc_rollover_chain.json, which
gets wiped on every Render container restart (no persistent disk on the
Starter plan). Now persisted in the same Postgres that the rest of the
app uses, so the challenge survives deploys.

Falls back to a no-op (returning empty chain / accepting writes silently)
if the DB isn't available — so local dev still works.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, inspect, text

from database import Base, SessionLocal
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION

logger = logging.getLogger(__name__)


class RolloverDay(Base):
    """One day-slot of the rollover challenge (up to 6 picks per row)."""
    __tablename__ = "wc_rollover_days"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chain_start_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    day_number = Column(Integer, nullable=False)  # 1-TARGET_DAYS
    date = Column(String(10), nullable=False, index=True)
    picks = Column(Text, nullable=False)  # JSON list of pick dicts
    combined_odds = Column(Float, nullable=False)
    avg_confidence = Column(Float, nullable=False)
    status = Column(String(20), default="pending")  # pending | won | lost | void
    policy_version = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def _day_dict(r) -> Dict[str, Any]:
    """One stored day, with its joint probability restored.

    Days written before the key mismatch was fixed all hold the 0.5 default,
    so the probability is recomputed from the legs themselves whenever they
    carry confidences. The legs are the authoritative record — they were
    always persisted correctly — which repairs the existing chain rather than
    leaving it reporting a number nobody ever predicted.
    """
    picks = json.loads(r.picks)
    joint = 1.0
    have = False
    for p in picks:
        c = p.get("confidence")
        if c is None:
            have = False
            break
        joint *= float(c)
        have = True

    is_manual = bool(picks and all(p.get("editorial_manual") for p in picks))
    hit = None if is_manual else (round(joint, 4) if have else r.avg_confidence)
    return {
        "archive_id": r.id,
        "day_number": r.day_number,
        "date": r.date,
        "picks": picks,
        "combined_odds": r.combined_odds,
        "hit_probability": hit,
        # Kept under the old name too — the column and any older reader still
        # expect it, and it is the same quantity.
        "avg_confidence": hit,
        "status": r.status,
        "policy_version": r.policy_version,
        "editorial_manual": is_manual,
        "source": "admin_curated" if is_manual else "engine",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def load_chain(default_start_date: str) -> Dict[str, Any]:
    """Load the current chain from DB. Returns same shape as the old JSON."""
    try:
        db = SessionLocal()
        try:
            # Use the most recently started chain that's still active
            rows = (
                db.query(RolloverDay)
                .order_by(RolloverDay.chain_start_date.desc(), RolloverDay.day_number.asc())
                .all()
            )
            if not rows:
                return {"start_date": default_start_date, "days": [], "status": "active"}

            start_date = rows[0].chain_start_date
            days = [r for r in rows if r.chain_start_date == start_date]
            days.sort(key=lambda r: r.day_number)

            # Deduplicate by day_number (keep the first / oldest row)
            seen: set = set()
            unique_days = []
            for r in days:
                if r.day_number not in seen:
                    seen.add(r.day_number)
                    unique_days.append(r)

            return {
                "start_date": start_date,
                "status": "active",
                "days": [_day_dict(r) for r in unique_days],
            }
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover DB load failed (using empty chain): {e}")
        return {"start_date": default_start_date, "days": [], "status": "active"}


def history(limit_days: int = 90) -> List[Dict[str, Any]]:
    """Every rollover day in the window, across current and older chains."""
    cutoff = (
        datetime.utcnow() - timedelta(days=max(1, limit_days) - 1)
    ).strftime("%Y-%m-%d")
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(RolloverDay)
                .filter(RolloverDay.date >= cutoff)
                .order_by(RolloverDay.date.desc(), RolloverDay.day_number.desc())
                .all()
            )
            out = []
            seen = set()
            for row in rows:
                key = (row.chain_start_date, row.day_number)
                if key in seen:
                    continue
                seen.add(key)
                item = _day_dict(row)
                item["chain_start_date"] = row.chain_start_date
                out.append(item)
            return out
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover history load failed: {e}")
        return []


def append_day(chain_start_date: str, day: Dict[str, Any]) -> bool:
    """Append a single day-slot to the chain. Idempotent — skips if already exists."""
    try:
        db = SessionLocal()
        try:
            # Serialize automated and manual publication of the same WAT day.
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                       {"k": f"rollover:{day[\"date\"]}"})
            existing = db.query(RolloverDay).filter(
                RolloverDay.chain_start_date == chain_start_date,
                RolloverDay.day_number == day["day_number"],
            ).first()
            if existing:
                return True
            # An alternate chain may not publish a second stage on this day.
            if db.query(RolloverDay).filter(RolloverDay.date == day["date"]).first():
                logger.warning("Rollover date already claimed: %s", day["date"])
                return False
            from leagues.rollover_lifecycle import allow_append_day
            previous = (
                db.query(RolloverDay)
                .filter(RolloverDay.chain_start_date == chain_start_date)
                .order_by(RolloverDay.day_number.asc())
                .all()
            )
            prior_days = [
                {"day_number": old.day_number, "date": old.date,
                 "status": old.status}
                for old in previous
            ]
            if not allow_append_day(prior_days, day, chain_start_date):
                logger.warning(
                    "Blocked invalid rollover progression for %s stage %s",
                    chain_start_date, day.get("day_number"),
                )
                return False
            row = RolloverDay(
                chain_start_date=chain_start_date,
                day_number=day["day_number"],
                date=day["date"],
                picks=json.dumps(day.get("picks", [])),
                combined_odds=float(day.get("combined_odds", 1.0)),
                # The builder calls this `hit_probability`; the column predates
                # that name. Reading only `avg_confidence` meant the default
                # fired every single time, so every stored day claimed 0.5 and
                # the real joint probability was thrown away on save.
                avg_confidence=float(
                    day.get("hit_probability", day.get("avg_confidence", 0.5))
                ),
                status=day.get("status", "pending"),
                policy_version=PUBLISHED_SELECTION_POLICY_VERSION,
            )
            db.add(row)
            db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover DB append failed: {e}")
        return False


def update_day_status(date: str, status: str) -> bool:
    """Mark a chain day's status (won / lost). Returns True on success."""
    try:
        db = SessionLocal()
        try:
            row = db.query(RolloverDay).filter(RolloverDay.date == date).order_by(RolloverDay.chain_start_date.desc()).first()
            if not row:
                return False
            row.status = status
            row.updated_at = datetime.utcnow()
            db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover DB update failed: {e}")
        return False


def reset_chain(chain_start_date: str) -> bool:
    """Wipe the chain for a given start_date. Used when chain becomes stale."""
    try:
        db = SessionLocal()
        try:
            deleted = db.query(RolloverDay).filter(RolloverDay.chain_start_date == chain_start_date).delete()
            db.commit()
            logger.info(f"Reset rollover chain for {chain_start_date}: {deleted} rows removed")
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover DB reset failed: {e}")
        return False


def drop_pending_days(from_date: str) -> int:
    """Delete unsettled chain days on or after `from_date`. Returns the count.

    Used when the rule that built those days is found to be wrong — the days
    are regenerated on the next build under the current rule.

    Deliberately not `reset_chain`, which deletes the whole chain including
    settled days. The settled record contains the losses, and a track record
    that quietly drops its losing days is worthless. Only days that have not
    resolved, and have not started, are removed; day numbering continues from
    whatever settled history remains.
    """
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(RolloverDay)
                .filter(RolloverDay.status == "pending",
                        RolloverDay.date >= from_date)
                .all()
            )
            count = len(rows)
            for r in rows:
                db.delete(r)
            db.commit()
            if count:
                logger.info(f"Dropped {count} pending rollover day(s) from {from_date}")
            return count
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"drop_pending_days failed: {e}")
        return 0


def ensure_table():
    """Create the table if it doesn't exist yet. Safe to call multiple times."""
    try:
        from database import engine
        RolloverDay.__table__.create(bind=engine, checkfirst=True)
        existing = {column["name"] for column in inspect(engine).get_columns(
            RolloverDay.__tablename__
        )}
        if "policy_version" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE wc_rollover_days "
                    "ADD COLUMN policy_version VARCHAR(40)"
                ))
        logger.info("wc_rollover_days table ready")
    except Exception as e:
        logger.warning(f"Could not create wc_rollover_days table: {e}")


def cleanup_old_chains(keep_recent_chains: int = 3) -> int:
    """Preserve settled rollover evidence for calibration and loss audits.

    Previous scheduler cleanup deleted old won/lost chains after only three
    challenges. That biases historical analyses and erases evidence of losing
    selections. Size management belongs to a separately approved archival
    policy, never to routine result settlement.
    """
    return 0
