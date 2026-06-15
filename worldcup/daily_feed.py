"""
World Cup Daily Feed

Generates daily accumulator data from WC predictions in the same format
the frontend expects from /accumulators/today.

This fills the 2_odds, 5_odds, 10_odds, over_1_5, and rollover categories
using World Cup match predictions when regular league data is unavailable.

Rollover: 1 pick per day at 2-3 odds, 10-day rolling chain.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent / "data"

_accum_cache: dict = {"result": None, "ts": 0}
_ACCUM_CACHE_TTL = 3600  # 1 hour


def _load(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def _save(filename: str, data):
    with open(DATA_DIR / filename, "w") as f:
        json.dump(data, f, indent=2)


def _to_game(p: dict, tip: dict = None) -> dict:
    """Convert a WC prediction to the game format the frontend expects."""
    if tip is None:
        # Use main prediction
        prediction = p.get("prediction", "")
        prediction_type = p.get("prediction_key", "match_result")
        confidence = p.get("confidence", 0.5)
        odds = None
        # Try to get odds from best_odds
        bo = p.get("best_odds", {})
        if prediction_type == "home_win":
            odds = bo.get("home_win")
        elif prediction_type == "away_win":
            odds = bo.get("away_win")
        elif prediction_type == "draw":
            odds = bo.get("draw")
        elif prediction_type in ("over_2_5", "over_1_5"):
            odds = bo.get("over_2_5")
    else:
        prediction = tip.get("tip", "")
        prediction_type = tip.get("market", "match_result")
        confidence = tip.get("confidence", 0.5)
        odds = tip.get("odds")

    # League name: from prediction's data_quality (club) or default to WC
    league_name = (p.get("data_quality") or {}).get("league") or "FIFA World Cup 2026"
    is_club = (p.get("data_quality") or {}).get("source") == "club_odds"

    return {
        "fixture_id": hash(p.get("match_id", "")) % 1000000,
        "home_team": p.get("home_team", ""),
        "away_team": p.get("away_team", ""),
        "league": league_name,
        "date": p.get("commence_time", ""),
        "prediction": prediction,
        "prediction_type": prediction_type,
        "prediction_value": prediction,
        "readable_prediction": prediction,
        "confidence": confidence,
        "estimated_odds": odds or round(1.0 / max(confidence, 0.1), 2),
        "odds": odds,
        "real_odds": odds,
        "risk_score": 1.0 - confidence,
        "risk_level": p.get("risk_level", "medium"),
        "models_agreed": 3,
        "edge": 0.05,
        "expected_value": 0.1,
        "model_type": "club_odds" if is_club else "worldcup_ensemble",
        "home_team_logo": p.get("home_team_logo"),
        "away_team_logo": p.get("away_team_logo"),
        "league_logo": p.get("_league_logo") or "https://media.api-sports.io/football/leagues/1.png",
    }


def _club_match_to_prediction(m: dict) -> dict:
    """
    Convert a parsed club match (from club_odds.get_active_matches) into
    the same schema as a WC prediction, so build_daily_accumulators can
    merge them seamlessly.
    """
    pk = m.get("safe_pick", {})
    probs = m.get("probabilities", {})
    return {
        "match_id": m.get("match_id"),
        "home_team": m["home_team"],
        "away_team": m["away_team"],
        "home_team_logo": None,
        "away_team_logo": None,
        "commence_time": m["commence_time"],
        "prediction": pk.get("prediction", ""),
        "prediction_key": pk.get("market", "match_result"),
        "prediction_market": pk.get("market", "match_result"),
        "confidence": pk.get("confidence", 0.5),
        "risk_level": "low" if pk.get("confidence", 0) >= 0.65 else "medium",
        "probabilities": {
            "home_win": probs.get("home_win", 0.33),
            "draw": probs.get("draw", 0.33),
            "away_win": probs.get("away_win", 0.33),
        },
        "best_odds": m.get("best_odds", {}),
        "top_tips": [{
            "tip": pk.get("prediction", ""),
            "market": pk.get("market", "match_result"),
            "confidence": pk.get("confidence", 0.5),
            "odds": pk.get("odds"),
        }],
        "goals": {
            "over_2_5_prob": probs.get("over_2_5", 0.5),
            "under_2_5_prob": probs.get("under_2_5", 0.5),
            "over_1_5_prob": min(0.95, (probs.get("over_2_5") or 0.5) + 0.15),
            "btts_prob": 0.5,
            "expected_total": 2.5,
            "expected_home": 1.3,
            "expected_away": 1.2,
        },
        "value_bets": [],
        "data_quality": {
            "source": "club_odds",
            "league": m.get("league", "Club"),
            "ml_verified": pk.get("ml_verified", False),
            "ml_agreement": pk.get("ml_agreement", "n/a"),
            "ml_probability": pk.get("ml_probability"),
            "raw_confidence": pk.get("raw_confidence"),
        },
        "_league_logo": "https://media.api-sports.io/football/leagues/1.png",
    }


def _load_club_predictions() -> list:
    """
    Pull club matches via The Odds API and convert to prediction schema.
    Returns empty list on any failure — caller falls back to WC-only.
    """
    try:
        from worldcup.club_odds import get_active_matches
        club_matches = get_active_matches(days_ahead=2)
        return [_club_match_to_prediction(m) for m in club_matches]
    except Exception as e:
        logger.warning(f"Club odds unavailable: {e}")
        return []


def build_daily_accumulators(force: bool = False) -> dict:
    """
    Build accumulator categories from WC + club predictions for today.

    Returns data in the exact format the frontend expects from /accumulators/today.
    Cached for 1 hour to avoid burning API quota on every page load.
    """
    import time as _time
    now = _time.time()
    if not force and _accum_cache["result"] and (now - _accum_cache["ts"]) < _ACCUM_CACHE_TTL:
        return _accum_cache["result"]

    wc_predictions = _load("wc_predictions.json") or []
    club_predictions = _load_club_predictions()

    # Merge: club matches first (they're closer to today), then WC
    predictions = club_predictions + wc_predictions

    if not predictions:
        return None

    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    today_preds = [p for p in predictions if p["commence_time"][:10] == today]
    tomorrow_preds = [p for p in predictions if p["commence_time"][:10] == tomorrow]

    # Check if all of today's games have already kicked off.
    # If so, users need tomorrow's picks — today's are no longer actionable.
    all_today_started = False
    if today_preds:
        try:
            all_today_started = all(
                datetime.fromisoformat(p["commence_time"].replace("Z", "+00:00")).replace(tzinfo=None) <= now
                for p in today_preds
            )
        except Exception:
            all_today_started = False

    if today_preds and not all_today_started:
        # Some games haven't kicked off yet — show today
        day_preds = today_preds
        target_date = today
    elif tomorrow_preds:
        # All today's games started (or no games today) — show tomorrow
        day_preds = tomorrow_preds
        target_date = tomorrow
        if all_today_started:
            logger.info(f"All {len(today_preds)} games today already started — showing tomorrow's picks")
    elif today_preds:
        # No tomorrow preds available yet, keep showing today as fallback
        day_preds = today_preds
        target_date = today
    else:
        logger.info("No matches today or tomorrow — no daily accumulators")
        return None

    # Sort by confidence
    day_preds.sort(key=lambda p: p.get("confidence", 0), reverse=True)

    # Collect all tips
    all_tips = []
    for p in day_preds:
        for tip in p.get("top_tips", [{"tip": p["prediction"], "market": p.get("prediction_market", "match_result"), "confidence": p["confidence"]}]):
            all_tips.append({"pred": p, "tip": tip})

    all_tips.sort(key=lambda x: x["tip"]["confidence"], reverse=True)

    # ── 2 Odds: 2-3 safest picks combining to ~2x ──
    two_odds_picks = []
    used_2 = set()
    for t in all_tips:
        mid = t["pred"]["match_id"]
        if mid in used_2:
            continue
        if t["tip"]["confidence"] >= 0.55:
            two_odds_picks.append(t)
            used_2.add(mid)
        if len(two_odds_picks) >= 3:
            break

    two_odds_games = [_to_game(t["pred"], t["tip"]) for t in two_odds_picks]
    two_odds_total = 1.0
    for g in two_odds_games:
        two_odds_total *= g["estimated_odds"]

    # ── 5 Odds: 4-5 picks combining to ~5x ──
    five_odds_picks = []
    used_5 = set()
    for t in all_tips:
        mid = t["pred"]["match_id"]
        if mid in used_5:
            continue
        if t["tip"]["confidence"] >= 0.45:
            five_odds_picks.append(t)
            used_5.add(mid)
        if len(five_odds_picks) >= 5:
            break

    five_odds_games = [_to_game(t["pred"], t["tip"]) for t in five_odds_picks]
    five_odds_total = 1.0
    for g in five_odds_games:
        five_odds_total *= g["estimated_odds"]

    # ── 10 Odds: 5-7 riskier picks ──
    ten_odds_picks = []
    used_10 = set()
    for t in all_tips:
        mid = t["pred"]["match_id"]
        if mid in used_10:
            continue
        if t["tip"]["confidence"] >= 0.35:
            ten_odds_picks.append(t)
            used_10.add(mid)
        if len(ten_odds_picks) >= 7:
            break

    ten_odds_games = [_to_game(t["pred"], t["tip"]) for t in ten_odds_picks]
    ten_odds_total = 1.0
    for g in ten_odds_games:
        ten_odds_total *= g["estimated_odds"]

    # ── Over 1.5: safest goal picks ──
    over_picks = []
    used_o = set()
    for p in day_preds:
        if p["match_id"] in used_o:
            continue
        if p["goals"]["over_1_5_prob"] >= 0.65:
            game = _to_game(p)
            game["prediction"] = "Over 1.5 Goals"
            game["prediction_type"] = "over_1_5"
            game["confidence"] = p["goals"]["over_1_5_prob"]
            game["estimated_odds"] = round(1.0 / max(p["goals"]["over_1_5_prob"], 0.1), 2)
            over_picks.append(game)
            used_o.add(p["match_id"])
        if len(over_picks) >= 5:
            break

    over_total = 1.0
    for g in over_picks:
        over_total *= g["estimated_odds"]

    # ── Rollover: 10-day chain (persists days to rollover_db) ──
    # Must be the chain builder, not the single-day variant: the chain
    # store feeds the Telegram 09:00 post and the Rollover/Results pages.
    # _build_daily_rollover only produced today's picks, so the chain
    # stayed empty forever and those consumers saw nothing.
    rollover = _build_rollover(predictions, today)

    # Build response in frontend-expected format
    def mk_cat(games, total_odds, risk, selected=True, reason=None):
        if not selected or not games:
            return {"selected": False, "games": [], "total_odds": 0, "risk_level": risk, "reason": reason or "No picks available"}
        avg_conf = sum(g["confidence"] for g in games) / len(games) if games else 0
        return {
            "selected": True,
            "games": games,
            "total_odds": round(total_odds, 2),
            "risk_level": risk,
            "reason": None,
        }

    # On thin match days (e.g. a lone World Cup opener) the higher tiers
    # can't be built honestly — they'd just repeat the same single pick at
    # 1.1x while claiming "5 odds". Mark them unavailable with the reason
    # instead of shipping a misleading slip.
    n_matches = len({p["match_id"] for p in day_preds})
    match_word = "match" if n_matches == 1 else "matches"
    thin_reason = f"Only {n_matches} {match_word} today — not enough fixtures for this tier"
    five_ok = len(five_odds_games) >= 3 and five_odds_total >= 2.5
    ten_ok = len(ten_odds_games) >= 4 and ten_odds_total >= 4.0

    result = {
        "status": "success",
        "date": target_date,
        "source": "worldcup",
        "accumulators": {
            "2_odds": mk_cat(two_odds_games, two_odds_total, "Low"),
            "5_odds": mk_cat(five_odds_games, five_odds_total, "Medium",
                             selected=five_ok, reason=None if five_ok else thin_reason),
            "10_odds": mk_cat(ten_odds_games, ten_odds_total, "High",
                              selected=ten_ok, reason=None if ten_ok else thin_reason),
            "over_1_5": mk_cat(over_picks, over_total, "Very Safe"),
            "rollover": rollover,
        },
    }

    _accum_cache["result"] = result
    _accum_cache["ts"] = _time.time()
    return result


def _safest_pick(p: dict) -> dict | None:
    """
    Find the single SAFEST tip for a match (highest confidence, not value).

    Considers (in preference order, all must clear confidence threshold):
    - Over 1.5 Goals (typically highest hit rate)
    - Strong favorite win (>=60% prob)
    - Double chance favorite-or-draw (very safe)
    """
    bo = p.get("best_odds", {})
    g = p.get("goals", {})
    probs = p.get("probabilities", {})
    candidates = []

    # Over 1.5 Goals — typically the safest single bet in football
    o15 = g.get("over_1_5_prob", 0)
    if o15 >= 0.70:
        est = round(1.0 / max(o15, 0.62), 2)  # Crude odds estimate
        if est >= 1.10:
            candidates.append((o15, est, "Over 1.5 Goals", "goals"))

    # Strong favorite Win
    for key, label, odds_key in [
        ("home_win", f"{p['home_team']} Win", "home_win"),
        ("away_win", f"{p['away_team']} Win", "away_win"),
    ]:
        odds = bo.get(odds_key)
        prob = probs.get(key, 0)
        if odds and odds >= 1.05 and prob >= 0.60:
            candidates.append((prob, odds, label, "match_result"))

    # Double chance (very safe)
    hw = probs.get("home_win", 0)
    aw = probs.get("away_win", 0)
    dr = probs.get("draw", 0)
    home_or_draw = min(0.95, hw + dr)
    away_or_draw = min(0.95, aw + dr)

    if home_or_draw >= 0.75:
        est = round(1.0 / max(home_or_draw, 0.55), 2)
        candidates.append((home_or_draw, est, f"{p['home_team']} or Draw", "double_chance"))
    if away_or_draw >= 0.75:
        est = round(1.0 / max(away_or_draw, 0.55), 2)
        candidates.append((away_or_draw, est, f"{p['away_team']} or Draw", "double_chance"))

    # Under 2.5 / BTTS only when extremely confident
    if g.get("under_2_5_prob", 0) >= 0.65 and bo.get("under_2_5"):
        candidates.append((g["under_2_5_prob"], bo["under_2_5"], "Under 2.5 Goals", "goals"))

    if not candidates:
        return None

    # Pick the highest confidence option
    candidates.sort(key=lambda x: x[0], reverse=True)
    prob, odds, label, market = candidates[0]
    return {
        "prediction": label,
        "odds": round(odds, 2),
        "confidence": round(prob, 3),
        "market": market,
    }


def _build_daily_rollover(day_preds: list, today: str) -> dict:
    """
    Daily rollover: pick the single SAFEST bet from today's matches.

    Unlike the old 10-day chain, this gives users 1 strong pick per day
    that they can roll their stake on. Fresh every day.
    """
    if not day_preds:
        return {
            "selected": False,
            "games": [],
            "total_odds": 0,
            "risk_level": "Low",
            "reason": "No matches today for rollover",
        }

    # Find safest pick across today's matches
    candidates = []
    for p in day_preds:
        pick = _safest_pick(p)
        if pick and pick["confidence"] >= 0.65:
            candidates.append({"pred": p, "pick": pick})

    if not candidates:
        return {
            "selected": False,
            "games": [],
            "total_odds": 0,
            "risk_level": "Low",
            "reason": "No confident enough picks for rollover today",
        }

    # Sort by confidence, take the best 1-2 picks
    candidates.sort(key=lambda x: x["pick"]["confidence"], reverse=True)
    chosen = candidates[:2]

    games = []
    total_odds = 1.0
    for c in chosen:
        p = c["pred"]
        pick = c["pick"]
        odds = pick.get("odds", 1.0)
        total_odds *= odds
        league_name = (p.get("data_quality") or {}).get("league") or "FIFA World Cup 2026"
        games.append({
            "fixture_id": hash(p.get("match_id", "")) % 1_000_000,
            "home_team": p.get("home_team", ""),
            "away_team": p.get("away_team", ""),
            "league": league_name,
            "date": p.get("commence_time", ""),
            "prediction": pick["prediction"],
            "prediction_type": pick.get("market", "match_result"),
            "confidence": pick["confidence"],
            "estimated_odds": odds,
            "odds": odds,
            "real_odds": odds,
            "home_team_logo": p.get("home_team_logo"),
            "away_team_logo": p.get("away_team_logo"),
            "risk_level": "low",
            "model_type": "rollover_daily",
        })

    avg_conf = sum(g["confidence"] for g in games) / len(games)
    return {
        "selected": True,
        "games": games,
        "total_odds": round(total_odds, 2),
        "num_games": len(games),
        "average_confidence": round(avg_conf, 4),
        "risk_level": "LOW" if avg_conf >= 0.75 else "MEDIUM",
        "recommendation": "INCLUDE",
        "reason": None,
    }


def _build_rollover(predictions: list, today: str) -> dict:
    """
    10-day SAFE rollover chain.

    Rules:
    - Each day slot = 1 to 3 SAFE picks (combined ~1.5-3.0 odds per slot)
    - Pick = highest-confidence option across all markets (NOT value-based)
    - No match repeats across the entire chain
    - Days with 0 safe picks are skipped — chain pulls from next match day instead
    - All picks in a slot must hit for that slot to count
    """
    chain_path = DATA_DIR / "wc_rollover_chain.json"

    # Primary store: Postgres (survives Render redeploys).
    # Fallback: legacy JSON file on disk (still works locally / when DB unreachable).
    try:
        from worldcup.rollover_db import load_chain as _db_load, append_day as _db_append, reset_chain as _db_reset
        db_available = True
    except Exception:
        db_available = False
        _db_load = _db_append = _db_reset = None  # type: ignore

    if db_available:
        chain = _db_load(today)
    elif chain_path.exists():
        with open(chain_path) as f:
            chain = json.load(f)
    else:
        chain = {"start_date": today, "days": [], "status": "active"}

    # Reset chain if start_date is too old
    if chain.get("start_date"):
        try:
            start = datetime.strptime(chain["start_date"], "%Y-%m-%d")
            if (datetime.now() - start).days > 30:
                if db_available and _db_reset:
                    _db_reset(chain["start_date"])
                chain = {"start_date": today, "days": [], "status": "active"}
        except Exception:
            chain = {"start_date": today, "days": [], "status": "active"}

    # Detect old chain schema (with 'prediction'/'odds' at day level instead of 'picks') and reset
    if chain.get("days") and "picks" not in chain["days"][0]:
        if db_available and _db_reset:
            _db_reset(chain.get("start_date", today))
        chain = {"start_date": today, "days": [], "status": "active"}

    # Track match IDs already used in the chain
    used_match_ids = set()
    for day in chain.get("days", []):
        for pick in day.get("picks", []):
            mid = pick.get("match_id")
            if mid:
                used_match_ids.add(mid)

    # Find safest pick for each upcoming, unused match
    upcoming = sorted(
        [p for p in predictions if p["commence_time"][:10] >= today and p["match_id"] not in used_match_ids],
        key=lambda p: p["commence_time"]
    )

    # Group by date, attach safe-pick
    by_date: dict[str, list] = {}
    for p in upcoming:
        pick = _safest_pick(p)
        if not pick:
            continue
        date = p["commence_time"][:10]
        by_date.setdefault(date, []).append({"pred": p, "pick": pick})

    # Don't add days before the last chain date
    last_date = chain["days"][-1]["date"] if chain.get("days") else ""

    # Add new day slots up to 10 total
    needed = 10 - len(chain.get("days", []))

    for date in sorted(by_date.keys()):
        if needed <= 0:
            break
        if date <= last_date:
            continue

        # Sort matches by pick confidence, take top 1-3
        day_matches = sorted(by_date[date], key=lambda x: x["pick"]["confidence"], reverse=True)
        # Cap: 3 picks max; 1 pick if the day has only 1 viable match
        chosen = day_matches[:3]

        if not chosen:
            continue

        picks_data = []
        combined = 1.0
        for m in chosen:
            p = m["pred"]
            pick = m["pick"]
            picks_data.append({
                "match_id": p["match_id"],
                "match": f"{p['home_team']} vs {p['away_team']}",
                "home_team": p["home_team"],
                "away_team": p["away_team"],
                "home_team_logo": p.get("home_team_logo"),
                "away_team_logo": p.get("away_team_logo"),
                "commence_time": p["commence_time"],
                "prediction": pick["prediction"],
                "market": pick["market"],
                "odds": pick["odds"],
                "confidence": pick["confidence"],
                "status": "pending",
            })
            combined *= pick["odds"]
            used_match_ids.add(p["match_id"])

        new_day = {
            "day_number": len(chain["days"]) + 1,
            "date": date,
            "picks": picks_data,
            "combined_odds": round(combined, 2),
            "avg_confidence": round(sum(pk["confidence"] for pk in picks_data) / len(picks_data), 3),
            "status": "pending",
        }
        chain["days"].append(new_day)
        needed -= 1

        # Persist: DB primary, JSON fallback
        if db_available and _db_append:
            if not _db_append(chain["start_date"], new_day):
                logger.error(f"Rollover day {new_day['day_number']} ({new_day['date']}) NOT persisted — results checker won't see it")
                _save("wc_rollover_chain.json", chain)
        else:
            _save("wc_rollover_chain.json", chain)

    # Calculate cumulative odds (product of each day's combined_odds)
    cum_odds = 1.0
    for d in chain.get("days", []):
        cum_odds *= d.get("combined_odds", 1.0)

    # Build legacy games list (flatten today's picks into game objects)
    today_day = next((d for d in chain.get("days", []) if d["date"] >= today and d.get("status") == "pending"), None)
    games = []
    if today_day:
        for pk in today_day.get("picks", []):
            games.append({
                "fixture_id": hash(pk.get("match_id", "")) % 1_000_000,
                "home_team": pk.get("home_team", ""),
                "away_team": pk.get("away_team", ""),
                "league": "FIFA World Cup 2026",
                "date": pk.get("commence_time", ""),
                "prediction": pk.get("prediction", ""),
                "prediction_type": pk.get("market", "match_result"),
                "confidence": pk.get("confidence", 0.5),
                "estimated_odds": pk.get("odds"),
                "odds": pk.get("odds"),
                "home_team_logo": pk.get("home_team_logo"),
                "away_team_logo": pk.get("away_team_logo"),
                "risk_level": "low",
                "model_type": "worldcup_safe",
            })

    return {
        "selected": True,
        "games": games,
        "total_odds": round(cum_odds, 2),
        "risk_level": "Challenge",
        "reason": None,
        "chain": chain.get("days", []),
        "chain_length": len(chain.get("days", [])),
        "target_days": 10,
        "cumulative_odds": round(cum_odds, 2),
    }
