"""
PostgreSQL persistence for the rollover chain.

The chain previously lived in worldcup/data/wc_rollover_chain.json, which
gets wiped on every Render container restart (no persistent disk on the
Starter plan). Now persisted in the same Postgres that the rest of the
app uses, so the 10-day chain survives deploys.

Falls back to a no-op (returning empty chain / accepting writes silently)
if the DB isn't available — so local dev still works.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, Integer, String, Text, DateTime, Float

from database import Base, SessionLocal

logger = logging.getLogger(__name__)


class RolloverDay(Base):
    """One day-slot of the WC rollover chain (1-3 picks per row)."""
    __tablename__ = "wc_rollover_days"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chain_start_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    day_number = Column(Integer, nullable=False)  # 1-10
    date = Column(String(10), nullable=False, index=True)
    picks = Column(Text, nullable=False)  # JSON list of pick dicts
    combined_odds = Column(Float, nullable=False)
    avg_confidence = Column(Float, nullable=False)
    status = Column(String(20), default="pending")  # pending | won | lost | void
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
                "days": [
                    {
                        "day_number": r.day_number,
                        "date": r.date,
                        "picks": json.loads(r.picks),
                        "combined_odds": r.combined_odds,
                        "avg_confidence": r.avg_confidence,
                        "status": r.status,
                    }
                    for r in unique_days
                ],
            }
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover DB load failed (using empty chain): {e}")
        return {"start_date": default_start_date, "days": [], "status": "active"}


def append_day(chain_start_date: str, day: Dict[str, Any]) -> bool:
    """Append a single day-slot to the chain. Idempotent — skips if already exists."""
    try:
        db = SessionLocal()
        try:
            existing = db.query(RolloverDay).filter(
                RolloverDay.chain_start_date == chain_start_date,
                RolloverDay.day_number == day["day_number"],
            ).first()
            if existing:
                return True
            row = RolloverDay(
                chain_start_date=chain_start_date,
                day_number=day["day_number"],
                date=day["date"],
                picks=json.dumps(day.get("picks", [])),
                combined_odds=float(day.get("combined_odds", 1.0)),
                avg_confidence=float(day.get("avg_confidence", 0.5)),
                status=day.get("status", "pending"),
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


def ensure_table():
    """Create the table if it doesn't exist yet. Safe to call multiple times."""
    try:
        from database import engine
        RolloverDay.__table__.create(bind=engine, checkfirst=True)
        logger.info("wc_rollover_days table ready")
    except Exception as e:
        logger.warning(f"Could not create wc_rollover_days table: {e}")


def cleanup_old_chains(keep_recent_chains: int = 3) -> int:
    """
    Remove old completed chains from the DB.

    Keeps the most recent `keep_recent_chains` chain_start_date groups.
    Anything older is deleted. Returns the number of rows removed.

    Run periodically (e.g. weekly) to keep the table tidy.
    """
    try:
        db = SessionLocal()
        try:
            # Get distinct start dates, newest first
            rows = (
                db.query(RolloverDay.chain_start_date)
                .distinct()
                .order_by(RolloverDay.chain_start_date.desc())
                .all()
            )
            all_starts = [r[0] for r in rows]
            if len(all_starts) <= keep_recent_chains:
                return 0  # Nothing to clean

            old_starts = all_starts[keep_recent_chains:]
            deleted = (
                db.query(RolloverDay)
                .filter(RolloverDay.chain_start_date.in_(old_starts))
                .delete(synchronize_session=False)
            )
            db.commit()
            logger.info(f"Cleaned up {deleted} rows from {len(old_starts)} old chains")
            return deleted
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Rollover cleanup failed: {e}")
        return 0
