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
_ACCUM_CACHE_TTL = 3600  # 1 hour

TARGET_DAYS = 10  # rollover chain length


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
    from leagues.selection import select_accumulator
    from leagues.picks import to_game

    all_picks, fixtures = run_pipeline(days_ahead=4, force=force)
    if not all_picks:
        return None

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # Fixtures that already kicked off are filtered upstream, so "today" goes
    # thin late in the day. Roll forward to the next date that can actually
    # support a slip rather than publishing a one-game card.
    day_picks = picks_for_date(today, all_picks)
    target_date = today
    if len({p["match_id"] for p in day_picks}) < 3:
        for offset in range(1, 5):
            nxt = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
            nxt_picks = picks_for_date(nxt, all_picks)
            if len({p["match_id"] for p in nxt_picks}) >= 3:
                day_picks, target_date = nxt_picks, nxt
                break

    if not day_picks:
        return None

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
        "total_fixtures": len({p["match_id"] for p in day_picks}),
        "accumulators": {
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

    _accum_cache.update({"result": result, "ts": now_ts})
    return result


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

    return {
        "selected": bool(games),
        "games": games,
        "total_odds": round(cumulative, 2),
        "risk_level": "Challenge",
        "reason": None if games else "No safe rollover slot for today",
        "chain": chain.get("days", []),
        "chain_length": len(chain.get("days", [])),
        "target_days": TARGET_DAYS,
        "cumulative_odds": round(cumulative, 2),
        "today_hit_probability": today_day.get("hit_probability") if today_day else None,
    }
