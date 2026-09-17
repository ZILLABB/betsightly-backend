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
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from database import Base, SessionLocal
from leagues.policy_version import (
    PUBLISHED_SELECTION_POLICY_VERSION as PUBLISHED_POLICY_VERSION,
    sample_readiness,
)

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
    # Historical rows pre-date versioned publishing and remain NULL. New rows
    # identify the policy generation that produced the public record.
    policy_version = Column(String(40), nullable=True)
    selection_fingerprint = Column(String(64), nullable=True)
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
        "policy_version": "VARCHAR(40)",
        "selection_fingerprint": "VARCHAR(64)",
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
                    "league_slug": g.get("league_slug"),
                    "competition_type": g.get("competition_type"),
                    "competition_region": g.get("competition_region"),
                    "team_type": g.get("team_type"),
                    "competition_stage": g.get("competition_stage"),
                    "competition_round": g.get("competition_round"),
                    "competition_context_label": g.get("competition_context_label"),
                    "neutral_venue": g.get("neutral_venue", False),
                    "knockout": g.get("knockout", False),
                    "leg_number": g.get("leg_number"),
                    "base_rate_source": g.get("base_rate_source"),
                    "competition_historical_sample": g.get("competition_historical_sample", 0),
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
                from leagues.booking import leg_fingerprint
                db.add(PublishedSlip(
                    date=date, category=category, picks=payload,
                    total_odds=total_odds, hit_probability=hit_probability,
                    presentation=presentation,
                    policy_version=PUBLISHED_POLICY_VERSION,
                    selection_fingerprint=leg_fingerprint(games),
                    status="pending",
                ))
            db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"archive_slip failed ({date}/{category}): {e}")
        return False


def history_cutoff(limit_days: int, as_of: date_type | str | None = None) -> str:
    """Inclusive calendar cutoff for an N-day window (today counts as day 1)."""
    if isinstance(as_of, str):
        anchor = datetime.strptime(as_of[:10], "%Y-%m-%d").date()
    else:
        anchor = as_of or datetime.now(timezone.utc).date()
    return (anchor - timedelta(days=max(1, int(limit_days)) - 1)).isoformat()


def get_history(limit_days: int = 30, category: Optional[str] = None,
                as_of: date_type | str | None = None) -> list[dict]:
    """Published slips inside a true rolling calendar window, newest first."""
    try:
        db = SessionLocal()
        try:
            q = db.query(PublishedSlip).filter(
                PublishedSlip.date >= history_cutoff(limit_days, as_of)
            )
            if category:
                q = q.filter(PublishedSlip.category == category)
            rows = q.order_by(
                PublishedSlip.date.desc(), PublishedSlip.id.desc()
            ).all()
            return [
                {
                    "archive_id": r.id,
                    "date": r.date,
                    "category": r.category,
                    "status": r.status,
                    "presentation": r.presentation or "accumulator",
                    "policy_version": r.policy_version,
                    "selection_fingerprint": r.selection_fingerprint,
                    "total_odds": r.total_odds,
                    "hit_probability": r.hit_probability,
                    "picks": json.loads(r.picks or "[]"),
                    "settled_at": r.settled_at.isoformat() if r.settled_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"get_history failed: {e}")
        return []


def pending_slips(before_date: str) -> list[Any]:
    """Slips with any leg still to resolve, on or before `before_date`.

    Deliberately not "slips whose status is pending". An accumulator dies on
    its first losing leg and was then dropped from this query, so every leg
    kicking off *later* stayed pending forever — 73 of 343 legs in decided
    slips, every one of them inside a slip that had already lost.

    Those legs never reached the calibrator, which fits only on settled
    outcomes, so the sample kept the leg that killed each slip and silently
    discarded the ones beside it. The slip's own outcome is still decided once
    and never revised; this only finishes recording what actually happened.
    """
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(PublishedSlip)
                .filter(PublishedSlip.date <= before_date)
                .order_by(PublishedSlip.date.desc())
                .limit(600)
                .all()
            )
            out = []
            for r in rows:
                if r.status == "pending":
                    out.append(r)
                    continue
                try:
                    if any(p.get("status") in (None, "pending")
                           for p in json.loads(r.picks or "[]")):
                        out.append(r)
                except Exception:
                    continue
            return out
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

            already_decided = slip.status in ("won", "lost", "void")

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
            elif pick_results and all(o == "void" for o in pick_results):
                # Every leg voided: the stake comes back. Counting that as a
                # win inflated the banker record by two slips that never
                # actually won anything.
                status = "void"
            elif all(o in ("won", "void") for o in pick_results) and pick_results:
                status = "won"
            else:
                status = "pending"

            slip.picks = json.dumps(picks)
            # A decided slip keeps its verdict — a leg finishing afterwards
            # completes the record, it does not reopen the result.
            if status != "pending" and not already_decided:
                slip.status = status
                slip.settled_at = datetime.utcnow()
            db.commit()
            return slip.status if already_decided else status
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"settle_slip failed: {e}")
        return None


def settled_accumulator_return(slip: dict) -> tuple[float, str]:
    """One-unit settled return and its evidence source.

    Settled leg outcomes are authoritative: wins retain their quoted price and
    void/DNB-push legs contribute 1.00. A legacy winning row without usable
    leg outcomes falls back to its published total rather than being silently
    turned into a zero return.
    """
    status = slip.get("status")
    if status == "lost":
        return 0.0, "settled_legs"
    if status == "void":
        return 1.0, "settled_legs"
    picks = slip.get("picks") or []
    states = [pick.get("status") for pick in picks]
    usable = bool(states) and all(state in ("won", "void") for state in states)
    if status == "won" and usable:
        returned = 1.0
        for pick in picks:
            if pick.get("status") == "won":
                try:
                    odds = float(pick.get("odds"))
                except (TypeError, ValueError):
                    usable = False
                    break
                if odds <= 1.0:
                    usable = False
                    break
                returned *= odds
        if usable:
            return round(returned, 6), "settled_leg_odds"
    try:
        return float(slip.get("total_odds") or 0), "legacy_total_odds"
    except (TypeError, ValueError):
        return 0.0, "legacy_total_odds"


def _booking_records(cutoff: str) -> dict[tuple[str, str], dict]:
    try:
        from leagues.booking import booking_history
        return booking_history(cutoff)
    except Exception as exc:
        logger.debug(f"booking performance unavailable: {exc}")
        return {}


def _exact_validated_booking(slip: dict, booking: dict | None) -> float | None:
    if not booking or booking.get("status") != "active":
        return None
    if str(booking.get("readback_validation") or "").upper() != "PASSED":
        return None
    actual = booking.get("actual_sportybet_odds")
    if actual is None:
        return None
    from leagues.booking import leg_fingerprint
    fingerprint = slip.get("selection_fingerprint") or leg_fingerprint(
        slip.get("picks") or []
    )
    original = booking.get("leg_fingerprint")
    variant = booking.get("booking_variant_fingerprint") or original
    if not fingerprint or fingerprint != original or variant != original:
        return None
    if int(booking.get("booked_leg_count") or booking.get("legs") or 0) != len(
        slip.get("picks") or []
    ):
        return None
    # An aggregate readback price cannot tell us the price of a leg removed by
    # a later void. Exclude that slip from the SportyBet ROI sample rather than
    # falsely preserving the original aggregate price.
    if any(pick.get("status") == "void" for pick in slip.get("picks") or []):
        return None
    try:
        value = float(actual)
        return value if value > 1.0 else None
    except (TypeError, ValueError):
        return None


def performance_summary(limit_days: int = 90,
                        policy_version: str | None = None) -> dict:
    """Aggregate win rate per category, plus profit on level 1-unit stakes."""
    history = get_history(limit_days=limit_days)
    if policy_version is not None:
        history = [row for row in history
                   if row.get("policy_version") == policy_version]
    bookings = _booking_records(history_cutoff(limit_days))
    by_cat: dict[str, dict] = {}
    for slip in history:
        if slip["status"] not in ("won", "lost"):
            continue
        c = by_cat.setdefault(slip["category"], {
            "won": 0, "lost": 0, "staked": 0.0, "returned": 0.0,
            "return_sources": {}, "real_odds_records": 0,
            "estimated_odds_records": 0,
            "_bookable_won": 0, "_bookable_lost": 0,
            "_bookable_staked": 0.0, "_bookable_returned": 0.0,
        })

        c["unit"] = "slip"

        # Over 1.5 has always been a singles product. Some legacy rows were
        # written before `presentation` existed (or retained its accumulator
        # default), so read-time accounting must not depend on a repair job.
        # This interprets the record defensively without mutating history.
        is_singles = (
            slip.get("presentation") == "singles"
            or slip.get("category") == "over_1_5"
        )
        if is_singles:
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
        else:
            c["lost"] += 1
        returned, source = settled_accumulator_return(slip)
        c["returned"] += returned
        c["return_sources"][source] = c["return_sources"].get(source, 0) + 1
        c["staked"] += 1.0
        if all(bool(pick.get("odds_are_real")) for pick in slip.get("picks") or []):
            c["real_odds_records"] += 1
        else:
            c["estimated_odds_records"] += 1

        booking = bookings.get((slip["date"], slip["category"]))
        actual_odds = _exact_validated_booking(slip, booking)
        if actual_odds is not None:
            c["_bookable_staked"] += 1.0
            if slip["status"] == "won":
                c["_bookable_won"] += 1
                c["_bookable_returned"] += actual_odds
            else:
                c["_bookable_lost"] += 1

    for c in by_cat.values():
        settled = c["won"] + c["lost"]
        c["settled"] = settled
        c.setdefault("unit", "slip")
        c["win_rate"] = round(c["won"] / settled, 4) if settled else 0.0
        c["profit"] = round(c["returned"] - c["staked"], 2)
        c["roi"] = round((c["returned"] - c["staked"]) / c["staked"], 4) if c["staked"] else 0.0
        c["published_odds_roi"] = c["roi"]
        c["published_record"] = {
            "settled": settled, "staked": c["staked"],
            "returned": round(c["returned"], 4), "profit": c["profit"],
            "roi": c["roi"], "return_sources": c["return_sources"],
            "real_odds_records": c["real_odds_records"],
            "estimated_odds_records": c["estimated_odds_records"],
        }
        bookable_staked = c.pop("_bookable_staked")
        bookable_returned = c.pop("_bookable_returned")
        bookable_won = c.pop("_bookable_won")
        bookable_lost = c.pop("_bookable_lost")
        bookable_profit = bookable_returned - bookable_staked
        c["bookable_sportybet_roi"] = (
            round(bookable_profit / bookable_staked, 4)
            if bookable_staked else None
        )
        c["bookable_record"] = {
            "settled": int(bookable_staked), "won": bookable_won,
            "lost": bookable_lost, "staked": bookable_staked,
            "returned": round(bookable_returned, 4),
            "profit": round(bookable_profit, 2),
            "roi": c["bookable_sportybet_roi"],
            "coverage": round(bookable_staked / c["staked"], 4)
            if c["staked"] else 0.0,
        }
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
    from leagues.forecast_observations import collect_forecast_observations
    observations = collect_forecast_observations(limit_days=limit_days)
    legs = [(row["probability"], row["won"]) for row in observations]

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
        "raw_observations": sum(row["duplicate_count"] for row in observations),
        "duplicates_removed": (
            sum(row["duplicate_count"] for row in observations) - total
        ),
        "current_policy": PUBLISHED_POLICY_VERSION,
        "current_policy_unique_forecasts": sum(
            row.get("policy_version") == PUBLISHED_POLICY_VERSION
            for row in observations
        ),
    }


def current_policy_performance(limit_days: int = 90) -> dict:
    """Reporting-only performance for the active public policy generation."""
    history = [row for row in get_history(limit_days=limit_days)
               if row.get("policy_version") == PUBLISHED_POLICY_VERSION]
    summary = performance_summary(
        limit_days=limit_days, policy_version=PUBLISHED_POLICY_VERSION
    )
    from leagues.forecast_observations import collect_forecast_observations
    observations = [row for row in collect_forecast_observations(limit_days)
                    if row.get("policy_version") == PUBLISHED_POLICY_VERSION]
    readiness = sample_readiness(len(observations))
    categories: dict[str, int] = {}
    for row in observations:
        for category in row.get("categories") or []:
            categories[category] = categories.get(category, 0) + 1
    slip_rows = [value for value in summary.values()
                 if value.get("unit") == "slip"]
    settled_slips = sum(value.get("settled", 0) for value in slip_rows)
    staked = sum(value.get("staked", 0.0) for value in slip_rows)
    returned = sum(value.get("returned", 0.0) for value in slip_rows)
    message = {
        "VERY_THIN": "Very thin current-policy sample; use as monitoring only.",
        "EARLY": "Early current-policy sample; not yet a stable estimate.",
        "PROVISIONAL": "Provisional current-policy sample; uncertainty remains high.",
        "USABLE": "Usable current-policy sample; keep sample size visible.",
        "STRONG": "Strong current-policy sample.",
        "MATURE": "Mature current-policy sample.",
    }[readiness["readiness"]]
    try:
        from leagues.calibrator import fit_calibration
        calibration_policy = fit_calibration().get("policy", {})
    except Exception as exc:
        logger.debug(f"current-policy calibration unavailable: {exc}")
        calibration_policy = {}
    return {
        "policy_version": PUBLISHED_POLICY_VERSION,
        "first_archived_date": min((row["date"] for row in history), default=None),
        "settled_unique_forecasts": len(observations),
        **readiness,
        "message": message,
        "category_forecast_samples": categories,
        "settled_slips": settled_slips,
        "staked": staked,
        "returned": round(returned, 4),
        "profit": round(returned - staked, 2),
        "roi": round((returned - staked) / staked, 4) if staked else None,
        "win_rate": round(
            sum(value.get("won", 0) for value in slip_rows) / settled_slips, 4
        ) if settled_slips else None,
        "average_predicted_probability": round(
            sum(row["probability"] for row in observations) / len(observations), 4
        ) if observations else None,
        "calibration": calibration_policy,
        "categories": summary,
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
            # Rollover is persisted separately and changes as days resolve.
            #
            # Card-level metadata is stored alongside the tiers under
            # underscore keys. Only the accumulators used to be saved, so
            # `first_published_at` — set when the card is built — vanished the
            # moment it locked, and the locked path served None. The whole
            # point of the field is to survive exactly that.
            body = {k: v for k, v in accumulators.items() if k != "rollover"}
            body["_first_published_at"] = datetime.utcnow().isoformat()
            body["_card_revision"] = 1
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
                    # Published tiers are immutable. Appending Over 1.5 picks
                    # without atomically extending its archive produced public
                    # singles that Results could never settle. Until revisioned
                    # archive rows exist, only an empty tier may be filled.
                    continue  # never replace a published tier wholesale

                if new_cat.get("selected") and new_cat.get("games"):
                    stored[key] = new_cat
                    filled.append(key)
            if filled:
                stored["_card_revision"] = int(stored.get("_card_revision", 1)) + 1
                stored["_last_updated_at"] = datetime.utcnow().isoformat()
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
