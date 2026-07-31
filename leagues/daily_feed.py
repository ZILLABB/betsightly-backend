"""
Daily feed — builds the categories and rollover chain the frontend consumes.

Everything here is downstream of leagues.engine.run_pipeline(), so every
published pick has passed through the same model: ESPN fixtures with real
DraftKings prices -> measured per-league base rates -> ELO second opinion
where available -> predictor -> pick construction -> selection.

Categories are selected by leagues.selection, which searches for the
combination most likely to land at each target multiplier instead of stacking
whatever looks most confident. Each category reports `hit_probability` — the
chance every leg wins — so a 10x slip is presented as the long shot it is.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent / "data"

_accum_cache: dict = {"result": None, "ts": 0}
_ACCUM_CACHE_TTL = 900  # 15 min — the card itself is locked, this just trims DB reads

TARGET_DAYS = 10  # rollover chain length

# Nigeria is UTC+1 year-round (no daylight saving), and the audience books in
# the morning. The card is published at 08:00 WAT so a full day of fixtures is
# still ahead of the user rather than half-gone.
WAT_OFFSET = timedelta(hours=1)
PUBLISH_HOUR_WAT = 8

# Fixtures kicking off sooner than this are left out at publish time — a pick
# a user cannot realistically get on is not a pick.
BOOKING_BUFFER = timedelta(minutes=20)


def _wat_now() -> datetime:
    return datetime.now(timezone.utc) + WAT_OFFSET


def _publish_date() -> str:
    """The WAT day whose card should currently be showing.

    Before 08:00 WAT the previous day's card is still the published one, so an
    early-morning visitor sees a settled, finished card rather than a
    half-built one for a day that has not opened yet.
    """
    wat = _wat_now()
    if wat.hour < PUBLISH_HOUR_WAT:
        wat -= timedelta(days=1)
    return wat.strftime("%Y-%m-%d")


def _save(filename: str, data):
    with open(DATA_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Categories ─────────────────────────────────────────────

def build_daily_accumulators(force: bool = False) -> dict:
    """Category picks + rollover chain for the next actionable match day."""
    import time as _time
    now_ts = _time.time()
    if not force and _accum_cache["result"] and (now_ts - _accum_cache["ts"]) < _ACCUM_CACHE_TTL:
        return _accum_cache["result"]

    from leagues.engine import run_pipeline, picks_for_date
    from leagues.selection import select_accumulator, select_banker
    from leagues.picks import to_game

    now = datetime.now(timezone.utc)
    publish_date = _publish_date()

    # Serve the locked card if today's has already been published. Re-selecting
    # through the day would quietly swap picks out from under anyone who booked
    # off the morning card.
    if not force:
        locked = _load_locked(publish_date)
        if locked:
            rollover = _build_rollover(_pipeline_for_rollover()[0], now.strftime("%Y-%m-%d"))
            locked["rollover"] = rollover
            result = {
                "status": "success",
                "date": publish_date,
                "source": "leagues",
                "published_at_wat": f"{PUBLISH_HOUR_WAT:02d}:00",
                "locked": True,
                "total_fixtures": sum(len(c.get("games", [])) for c in locked.values() if isinstance(c, dict)),
                "accumulators": _mark_started(locked, now),
            }
            _accum_cache.update({"result": result, "ts": now_ts})
            return result

    all_picks, fixtures = run_pipeline(days_ahead=4, force=force)
    if not all_picks:
        return None

    today = now.strftime("%Y-%m-%d")

    # Only fixtures a user can still get on. Anything already under way, or
    # about to be, is excluded from a freshly published card.
    bookable_from = (now + BOOKING_BUFFER).isoformat().replace("+00:00", "Z")
    all_picks = [p for p in all_picks if p["_fixture"]["commence_time"] >= bookable_from]
    if not all_picks:
        return None

    # Prefer the publishing day; fall back to the next day with enough fixtures
    # so a late-evening rebuild does not publish a one-game card.
    day_picks = picks_for_date(publish_date, all_picks)
    target_date = publish_date
    if len({p["match_id"] for p in day_picks}) < 3:
        for offset in range(0, 5):
            nxt = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
            nxt_picks = picks_for_date(nxt, all_picks)
            if len({p["match_id"] for p in nxt_picks}) >= 3:
                day_picks, target_date = nxt_picks, nxt
                break

    if not day_picks:
        return None

    banker = select_banker(day_picks)
    two = select_accumulator(day_picks, 2.0, max_picks=4, min_confidence=0.60, min_joint=0.38)
    five = select_accumulator(day_picks, 5.0, max_picks=5, min_confidence=0.48, min_joint=0.12)
    ten = select_accumulator(day_picks, 10.0, max_picks=6, min_confidence=0.40, min_joint=0.045)

    # Over 1.5 — one per fixture, safest first, only where the league's own
    # measured rate supports it (this is the market the old model overclaimed).
    over_picks, seen = [], set()
    for p in sorted(day_picks, key=lambda x: -x["confidence"]):
        if p["market"] != "over_1_5" or p["match_id"] in seen:
            continue
        if p["confidence"] < 0.70:
            continue
        over_picks.append(p)
        seen.add(p["match_id"])
        if len(over_picks) >= 5:
            break
    over_total, over_joint = 1.0, 1.0
    for p in over_picks:
        over_total *= p["odds"]
        over_joint *= p["confidence"]

    rollover = _build_rollover(all_picks, today)

    def mk_cat(sel, risk, reason_if_empty):
        picks_, total, joint = sel
        if not picks_:
            return {"selected": False, "games": [], "total_odds": 0,
                    "risk_level": risk, "hit_probability": 0,
                    "reason": reason_if_empty}
        return {
            "selected": True,
            "games": [to_game(p) for p in picks_],
            "total_odds": round(total, 2),
            "risk_level": risk,
            "hit_probability": round(joint, 3),
            "reason": None,
        }

    thin = "Not enough matches today to build this safely — check back tomorrow."

    result = {
        "status": "success",
        "date": target_date,
        "source": "leagues",
        "published_at_wat": f"{PUBLISH_HOUR_WAT:02d}:00",
        "locked": False,
        "total_fixtures": len({p["match_id"] for p in day_picks}),
        "accumulators": {
            "banker": mk_cat(banker, "Banker", "No pick met the banker threshold today."),
            "2_odds": mk_cat(two, "Low", thin),
            "5_odds": mk_cat(five, "Medium", thin),
            "10_odds": mk_cat(ten, "High", thin),
            "over_1_5": mk_cat(
                (over_picks, over_total, over_joint) if over_picks else ([], 0, 0),
                "Very Safe", thin,
            ),
            "rollover": rollover,
        },
    }

    _archive(target_date, result["accumulators"])

    # Lock the card for the publishing day so it is served unchanged from here
    if target_date == publish_date:
        try:
            from leagues.picks_db import save_card
            save_card(publish_date, result["accumulators"])
            result["locked"] = True
        except Exception as e:
            logger.debug(f"card lock skipped: {e}")

    result["accumulators"] = _mark_started(result["accumulators"], now)
    _accum_cache.update({"result": result, "ts": now_ts})
    return result


def _load_locked(publish_date: str):
    try:
        from leagues.picks_db import load_card
        return load_card(publish_date)
    except Exception:
        return None


def _pipeline_for_rollover():
    """Picks needed to extend the rollover chain, independent of the locked card."""
    from leagues.engine import run_pipeline
    all_picks, _ = run_pipeline(days_ahead=4)
    return (all_picks,)


def _mark_started(accumulators: dict, now: datetime) -> dict:
    """Flag legs whose match has kicked off.

    The card stays fixed once published — that is the point — but a visitor
    arriving at midday still needs to see which legs are no longer bookable
    rather than being shown a slip that reads as if it were all still open.
    """
    cutoff = now.isoformat().replace("+00:00", "Z")
    for cat in accumulators.values():
        if not isinstance(cat, dict):
            continue
        games = cat.get("games") or []
        started = 0
        for g in games:
            ko = g.get("kickoff") or g.get("date") or ""
            g["started"] = bool(ko and ko <= cutoff)
            if g["started"]:
                started += 1
        if games:
            cat["started_count"] = started
            cat["all_started"] = started == len(games)
    return accumulators


def _archive(date: str, accumulators: dict) -> None:
    """Record today's slips so they can be settled and shown as history."""
    try:
        from leagues.picks_db import archive_slip
    except Exception:
        return
    for category, cat in accumulators.items():
        if category == "rollover" or not cat.get("selected"):
            continue
        try:
            archive_slip(
                date=date,
                category=category,
                games=cat.get("games", []),
                total_odds=cat.get("total_odds", 0),
                hit_probability=cat.get("hit_probability", 0),
            )
        except Exception as e:
            logger.debug(f"archive {category} failed: {e}")


# ── Rollover chain ─────────────────────────────────────────

def _build_rollover(all_picks: list, today: str) -> dict:
    """10-day chain, one slot per match day, persisted to Postgres."""
    from leagues.engine import picks_for_date
    from leagues.selection import select_rollover_day
    from leagues.picks import to_game

    try:
        from leagues.rollover_db import (
            load_chain as _db_load,
            append_day as _db_append,
            reset_chain as _db_reset,
            update_day_status as _db_update,
        )
        db_available = True
    except Exception:
        db_available = False
        _db_load = _db_append = _db_reset = _db_update = None  # type: ignore

    chain_path = DATA_DIR / "rollover_chain.json"
    if db_available:
        chain = _db_load(today)
    elif chain_path.exists():
        chain = json.loads(chain_path.read_text(encoding="utf-8"))
    else:
        chain = {"start_date": today, "days": [], "status": "active"}

    # Retire a chain that has drifted far past its start
    if chain.get("start_date"):
        try:
            start = datetime.strptime(chain["start_date"], "%Y-%m-%d")
            if (datetime.utcnow() - start).days > 45:
                if db_available:
                    _db_reset(chain["start_date"])
                chain = {"start_date": today, "days": [], "status": "active"}
        except Exception:
            chain = {"start_date": today, "days": [], "status": "active"}

    # Void days whose matches finished more than two days ago but never
    # resolved — otherwise one unresolvable day freezes the chain forever.
    stale_cutoff = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    for day in chain.get("days", []):
        if day.get("status") == "pending" and day.get("date", "") < stale_cutoff:
            day["status"] = "void"
            logger.info(f"Voiding stale rollover day {day.get('date')}")
            if db_available:
                try:
                    _db_update(day["date"], "void")
                except Exception:
                    pass

    # Start fresh once the chain is complete
    if len(chain.get("days", [])) >= TARGET_DAYS:
        if all(d.get("status") in ("won", "lost", "void") for d in chain["days"]):
            logger.info(f"Chain {chain.get('start_date')} complete — starting a new one")
            chain = {"start_date": today, "days": [], "status": "active"}

    used_matches = {
        pk.get("match_id")
        for day in chain.get("days", [])
        for pk in day.get("picks", [])
        if pk.get("match_id")
    }

    # Group remaining picks by match day
    by_date: dict[str, list] = {}
    for p in all_picks:
        if p["match_id"] in used_matches:
            continue
        d = p["_fixture"]["commence_time"][:10]
        if d >= today:
            by_date.setdefault(d, []).append(p)

    last_date = chain["days"][-1]["date"] if chain.get("days") else ""
    needed = TARGET_DAYS - len(chain.get("days", []))

    for date in sorted(by_date):
        if needed <= 0:
            break
        if date <= last_date:
            continue
        chosen, combined, joint = select_rollover_day(by_date[date])
        if not chosen:
            continue

        new_day = {
            "day_number": len(chain["days"]) + 1,
            "date": date,
            "status": "pending",
            "combined_odds": round(combined, 2),
            "hit_probability": round(joint, 3),
            "picks": [
                {
                    "match_id": p["match_id"],
                    "match": f"{p['_fixture']['home']['name']} vs {p['_fixture']['away']['name']}",
                    "home_team": p["_fixture"]["home"]["name"],
                    "away_team": p["_fixture"]["away"]["name"],
                    "home_team_logo": p["_fixture"]["home"].get("logo"),
                    "away_team_logo": p["_fixture"]["away"].get("logo"),
                    "league": p["_fixture"]["league"],
                    "commence_time": p["_fixture"]["commence_time"],
                    "prediction": p["prediction"],
                    "market": p["market_group"],
                    "odds": p["odds"],
                    "odds_are_real": p["odds_are_real"],
                    "confidence": p["confidence"],
                    "status": "pending",
                }
                for p in chosen
            ],
        }
        chain["days"].append(new_day)
        needed -= 1

        if db_available:
            if not _db_append(chain["start_date"], new_day):
                logger.error(f"Rollover day {new_day['date']} not persisted")
                _save("rollover_chain.json", chain)
        else:
            _save("rollover_chain.json", chain)

    cumulative = 1.0
    for d in chain.get("days", []):
        cumulative *= d.get("combined_odds", 1.0)

    today_day = next(
        (d for d in chain.get("days", []) if d["date"] >= today and d.get("status") == "pending"),
        None,
    )
    games = []
    if today_day:
        for pk in today_day.get("picks", []):
            games.append({
                "fixture_id": abs(hash(pk.get("match_id", ""))) % 1_000_000,
                "match_id": pk.get("match_id"),
                "home_team": pk.get("home_team", ""),
                "away_team": pk.get("away_team", ""),
                "home_team_logo": pk.get("home_team_logo"),
                "away_team_logo": pk.get("away_team_logo"),
                "league": pk.get("league", ""),
                "date": pk.get("commence_time", ""),
                "kickoff": pk.get("commence_time", ""),
                "prediction": pk.get("prediction", ""),
                "prediction_type": pk.get("market", "match_result"),
                "confidence": pk.get("confidence", 0.5),
                "estimated_odds": pk.get("odds"),
                "odds": pk.get("odds"),
                "real_odds": pk.get("odds") if pk.get("odds_are_real") else None,
                "odds_are_real": pk.get("odds_are_real", False),
                "risk_level": "low",
                "model_type": "market_poisson",
            })

    today_odds = today_day.get("combined_odds", 0) if today_day else 0

    return {
        "selected": bool(games),
        "games": games,
        # The multiplier for today's slot — the number a user actually stakes
        # against. The compounded figure is `cumulative_odds`; publishing that
        # as total_odds made the category tab advertise "1746x".
        "total_odds": round(today_odds, 2),
        "risk_level": "Challenge",
        "reason": None if games else "No safe rollover slot for today",
        "chain": chain.get("days", []),
        "chain_length": len(chain.get("days", [])),
        "target_days": TARGET_DAYS,
        "cumulative_odds": round(cumulative, 2),
        "today_hit_probability": today_day.get("hit_probability") if today_day else None,
    }
