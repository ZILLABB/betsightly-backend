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
    # "accumulator" (every leg must land) or "singles" (each leg is its own
    # bet). They settle and score by completely different rules, so the slip
    # has to remember which it was published as.
    presentation = Column(String(16), default="accumulator")
    status = Column(String(20), default="pending")             # pending|won|lost|void
    settled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_table() -> bool:
    try:
        from database import engine
        Base.metadata.create_all(bind=engine, tables=[PublishedSlip.__table__])
        _add_missing_columns(engine)
        return True
    except Exception as e:
        logger.warning(f"Could not ensure published_slips table: {e}")
        return False


def _add_missing_columns(engine) -> None:
    """Add columns introduced after the table was first created.

    create_all() only creates tables that do not exist — it will not alter one
    that does. On a database where published_slips already exists, a new column
    is simply absent and every read of it fails at runtime rather than at
    deploy. The project has no migration discipline (one Alembic revision,
    everything else via create_all), so additive columns are applied here.

    The existing columns are inspected rather than relying on
    "ADD COLUMN IF NOT EXISTS": Postgres supports that, SQLite does not, and
    production is Postgres while local dev is SQLite. Checking first works on
    both and keeps this safe to run on every boot.
    """
    import sqlalchemy as sa

    wanted = {
        "presentation": "VARCHAR(16) DEFAULT 'accumulator'",
    }
    try:
        existing = {c["name"] for c in sa.inspect(engine).get_columns("published_slips")}
    except Exception as e:
        logger.warning(f"could not inspect published_slips: {e}")
        return

    for name, ddl in wanted.items():
        if name in existing:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(
                    f"ALTER TABLE published_slips ADD COLUMN {name} {ddl}"))
            logger.info(f"published_slips: added column {name}")
        except Exception as e:
            logger.warning(f"could not add column {name}: {e}")


def archive_slip(date: str, category: str, games: list[dict],
                 total_odds: float, hit_probability: float,
                 presentation: str = "accumulator") -> bool:
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
                    # The uncorrected model probability. The calibrator has to
                    # refit against the number it corrects, or once calibrated
                    # legs start settling it would fit a shift on top of a
                    # shift and correct the same bias twice.
                    "raw_confidence": g.get("raw_confidence"),
                    # The trained ensemble's shadow opinion, stored so it can
                    # be scored against the same outcome as the published pick.
                    "ml_confidence": g.get("ml_confidence"),
                    "home_team_logo": g.get("home_team_logo"),
                    "away_team_logo": g.get("away_team_logo"),
                    "status": "pending",
                }
                for g in games
            ])

            if existing:
                # The archive is the published record: first write wins. It
                # previously overwrote while pending, so as early fixtures
                # kicked off and selection re-ran, the "record" of what we had
                # tipped quietly changed underneath us.
                return True
            else:
                db.add(PublishedSlip(
                    date=date, category=category, picks=payload,
                    total_odds=total_odds, hit_probability=hit_probability,
                    presentation=presentation, status="pending",
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
                    "presentation": r.presentation or "accumulator",
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

    An accumulator wins only when every leg wins, and is lost the moment any
    leg loses — a lost leg cannot be recovered, so there is no point waiting.

    A singles tier is scored completely differently and applying the
    accumulator rule to it was badly wrong. Over 1.5 publishes ten independent
    bets; on 19 August one lost while nine were still unplayed and the whole
    tier was recorded LOST. Over time that makes a tier hitting eight from ten
    read as though it loses almost every day.

    Singles stay pending until every leg has resolved, and are then judged on
    whether the set of bets made money at one unit each — which is the only
    question that means anything when nobody staked them as one slip.
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

            if (slip.presentation or "accumulator") == "singles":
                if not pick_results or any(o == "pending" for o in pick_results):
                    status = "pending"
                else:
                    staked = sum(1 for o in pick_results if o in ("won", "lost"))
                    returned = sum(
                        float(pk.get("odds") or 0)
                        for pk, o in zip(picks, pick_results) if o == "won"
                    )
                    status = "won" if returned > staked else "lost"
            elif any(o == "lost" for o in pick_results):
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

        c["unit"] = "slip"

        if slip.get("presentation") == "singles":
            # Counted in picks, not slips — the caller has to be able to tell,
            # or a page adding these to the accumulator counts reports ten
            # separate bets as ten slips.
            c["unit"] = "pick"
            # One unit per pick, not one unit on the set. Charging a singles
            # tier a single stake and paying it the product of ten prices would
            # be scoring a bet nobody placed.
            for leg in slip.get("picks", []):
                if leg.get("status") == "won":
                    c["won"] += 1
                    c["staked"] += 1.0
                    c["returned"] += float(leg.get("odds") or 0)
                elif leg.get("status") == "lost":
                    c["lost"] += 1
                    c["staked"] += 1.0
            continue

        if slip["status"] == "won":
            c["won"] += 1
            c["returned"] += slip["total_odds"]
        else:
            c["lost"] += 1
        c["staked"] += 1.0

    for c in by_cat.values():
        settled = c["won"] + c["lost"]
        c["settled"] = settled
        c.setdefault("unit", "slip")
        c["win_rate"] = round(c["won"] / settled, 4) if settled else 0.0
        c["profit"] = round(c["returned"] - c["staked"], 2)
        c["roi"] = round((c["returned"] - c["staked"]) / c["staked"], 4) if c["staked"] else 0.0
    return by_cat


# Confidence buckets used for calibration. Edges chosen so each band is wide
# enough to accumulate a usable sample before the site claims anything.
CALIBRATION_BUCKETS = [
    (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01),
]


def calibration(limit_days: int = 180) -> dict:
    """Predicted confidence vs measured hit rate, per confidence band.

    Answers the only question that matters about a probability: when we say
    70%, does it happen roughly 70% of the time? Draws on individual legs
    (not whole slips) from both the category archive and the rollover chain,
    since a leg is the thing a probability was actually attached to.

    Legs still pending or voided are excluded — only settled outcomes count.
    """
    legs: list[tuple[float, bool]] = []

    for slip in get_history(limit_days=limit_days):
        for leg in slip.get("picks", []):
            conf, status = leg.get("confidence"), leg.get("status")
            if conf is None or status not in ("won", "lost"):
                continue
            legs.append((float(conf), status == "won"))

    # Rollover legs carry the same confidences and are settled the same way
    try:
        from leagues.rollover_db import RolloverDay
        db = SessionLocal()
        try:
            for row in db.query(RolloverDay).all():
                for leg in json.loads(row.picks or "[]"):
                    conf, status = leg.get("confidence"), leg.get("status")
                    if conf is None or status not in ("won", "lost"):
                        continue
                    legs.append((float(conf), status == "won"))
        finally:
            db.close()
    except Exception:
        pass

    buckets = []
    for lo, hi in CALIBRATION_BUCKETS:
        sample = [won for conf, won in legs if lo <= conf < hi]
        n = len(sample)
        buckets.append({
            "range": f"{int(lo * 100)}-{int(hi * 100 if hi <= 1 else 100)}%",
            "low": lo,
            "high": min(hi, 1.0),
            "predicted": round((lo + min(hi, 1.0)) / 2, 3),
            "actual": round(sum(sample) / n, 4) if n else None,
            "sample": n,
        })

    total = len(legs)
    hit = sum(1 for _, won in legs if won)
    avg_pred = round(sum(c for c, _ in legs) / total, 4) if total else None

    return {
        "buckets": buckets,
        "total_legs": total,
        "hit_rate": round(hit / total, 4) if total else None,
        "avg_predicted": avg_pred,
        # Positive means we are over-confident: we promised more than we hit.
        "bias": round(avg_pred - (hit / total), 4) if total else None,
    }


# ── Locked daily card ──────────────────────────────────────

class DailyCard(Base):
    """The full published card for one publishing day, stored verbatim.

    The card is generated once per day and then served from here rather than
    re-selected on each request. Two reasons:

    - Fixtures that have kicked off are filtered out of the source feed, so
      re-selecting later in the day silently produces a *different* slip. The
      pick a user saw at 08:00 could vanish by noon, and the archived record
      would change with it — a track record that rewrites itself is worthless.
    - Regenerating is also wasted work; the selection is deterministic given
      the same fixtures.
    """
    __tablename__ = "daily_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    publish_date = Column(String(10), nullable=False, unique=True, index=True)
    payload = Column(Text, nullable=False)   # JSON: the accumulators block
    created_at = Column(DateTime, default=datetime.utcnow)


def ensure_card_table() -> bool:
    try:
        from database import engine
        Base.metadata.create_all(bind=engine, tables=[DailyCard.__table__])
        return True
    except Exception as e:
        logger.warning(f"Could not ensure daily_cards table: {e}")
        return False


def save_card(publish_date: str, accumulators: dict) -> bool:
    """Store the day's card. First write wins — the card is immutable."""
    try:
        db = SessionLocal()
        try:
            existing = db.query(DailyCard).filter(DailyCard.publish_date == publish_date).first()
            if existing:
                return True  # already locked for this day
            # Rollover is persisted separately and changes as days resolve
            body = {k: v for k, v in accumulators.items() if k != "rollover"}
            db.add(DailyCard(publish_date=publish_date, payload=json.dumps(body)))
            db.commit()
            logger.info(f"Locked daily card for {publish_date}")
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"save_card failed ({publish_date}): {e}")
        return False


def fill_empty_card_tiers(publish_date: str, fresh: dict) -> list[str]:
    """Fill tiers the locked card left empty. Never touches a published one.

    The card is immutable because a slip someone booked at 08:00 must not
    change under them. A tier that was published as *empty* carries no such
    promise — nobody can have staked it — so filling one in later adds to the
    card without rewriting any part of it.

    Deliberately one-directional: a tier that is already selected is skipped
    outright, so this cannot quietly restore the rewriting problem the lock
    exists to prevent. Returns the tiers it filled.
    """
    filled: list[str] = []
    try:
        db = SessionLocal()
        try:
            row = db.query(DailyCard).filter(DailyCard.publish_date == publish_date).first()
            if not row:
                return []
            stored = json.loads(row.payload)
            for key, new_cat in fresh.items():
                if key == "rollover" or not isinstance(new_cat, dict):
                    continue
                old_cat = stored.get(key)

                if isinstance(old_cat, dict) and old_cat.get("selected"):
                    # A tier of independent singles can be *extended* without
                    # rewriting it: the picks already published stay exactly as
                    # they are and remain valid on their own, and a new one
                    # neither changes nor depends on them. An accumulator is
                    # the opposite — adding a leg changes the bet — so this
                    # only ever applies to a singles tier, and only ever
                    # appends.
                    # Keyed on how the tier is defined *now*, not on what the
                    # stored payload happens to record. Cards written before
                    # `presentation` existed carry no such field, and requiring
                    # it on both sides meant the tier this was written for was
                    # the one case it skipped.
                    if new_cat.get("presentation") == "singles":
                        old_cat["presentation"] = "singles"
                        have = {g.get("match_id") for g in old_cat.get("games", [])}
                        extra = [g for g in new_cat.get("games", [])
                                 if g.get("match_id") not in have]
                        if extra:
                            old_cat["games"] = list(old_cat.get("games", [])) + extra
                            confs = [g.get("confidence") or 0 for g in old_cat["games"]]
                            old_cat["hit_probability"] = round(
                                sum(confs) / len(confs), 3) if confs else 0
                            total = 1.0
                            for g in old_cat["games"]:
                                total *= (g.get("odds") or 1.0)
                            old_cat["total_odds"] = round(total, 2)
                            stored[key] = old_cat
                            filled.append(f"{key}(+{len(extra)})")
                    continue  # never replace a published tier wholesale

                if new_cat.get("selected") and new_cat.get("games"):
                    stored[key] = new_cat
                    filled.append(key)
            if filled:
                row.payload = json.dumps(stored)
                db.commit()
                logger.info(f"Card {publish_date}: filled empty tiers {filled}")
            return filled
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"fill_empty_card_tiers failed ({publish_date}): {e}")
        return []


def load_card(publish_date: str) -> Optional[dict]:
    """The locked card for a day, or None if it has not been published yet."""
    try:
        db = SessionLocal()
        try:
            row = db.query(DailyCard).filter(DailyCard.publish_date == publish_date).first()
            return json.loads(row.payload) if row else None
        finally:
            db.close()
    except Exception:
        return None
