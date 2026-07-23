"""
Daily Feed — multi-league accumulator builder

Generates daily accumulator data from club-league predictions (ESPN fixtures
+ ELO ratings, plus bookmaker odds when the Odds API quota allows) in the
format the frontend expects from /accumulators/today.

Fills the 2_odds, 5_odds, 10_odds, over_1_5, and rollover categories.
Rollover: 2-5 safe picks per day (>=70% confidence) combining to 2-3x,
10-day rolling chain.
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
    league_name = (p.get("data_quality") or {}).get("league") or "Football"
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
        "model_type": "club_odds" if is_club else "elo_engine",
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
    club_preds = []
    try:
        from leagues.club_odds import get_active_matches
        club_matches = get_active_matches(days_ahead=2)
        club_preds = [_club_match_to_prediction(m) for m in club_matches]
    except Exception as e:
        logger.warning(f"Club odds unavailable: {e}")

    # ESPN + ELO source (no Odds API dependency). Merge, de-duped by teams+date.
    try:
        from leagues.club_fixtures import get_club_predictions
        seen = {f"{p['home_team']}|{p['away_team']}|{p['commence_time'][:10]}" for p in club_preds}
        for p in get_club_predictions(days_ahead=2):
            key = f"{p['home_team']}|{p['away_team']}|{p['commence_time'][:10]}"
            if key not in seen:
                club_preds.append(p)
                seen.add(key)
    except Exception as e:
        logger.warning(f"ESPN+ELO club fixtures unavailable: {e}")

    return club_preds


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

    predictions = _load_club_predictions()

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

    # Build a pool of all viable picks across today's matches (one best per match)
    # Uses _all_picks which reads real bookmaker odds + model probabilities
    pick_pool = []
    for p in day_preds:
        picks = _all_picks(p)
        if not picks:
            continue
        # Keep all picks from this match, tagged with match_id
        for pk in picks:
            pk["_match_id"] = p["match_id"]
            pk["_pred"] = p
        pick_pool.extend(picks)

    def _build_category(pool, target_max, max_picks):
        """Stack safe picks (all >70% confidence, one per match) up to a target."""
        MARKET_PREF = {"match_result": 1.3, "goals": 1.1, "btts": 1.2, "double_chance": 0.7}
        eligible = [pk for pk in pool if pk["confidence"] >= 0.70 and pk["odds"] >= 1.10]
        for pk in eligible:
            mw = MARKET_PREF.get(pk["market"], 1.0)
            pk["_cat_score"] = pk["confidence"] * pk["odds"] * mw
        eligible.sort(key=lambda x: x["_cat_score"], reverse=True)

        chosen = []
        used_matches = set()
        used_markets = {}
        combined = 1.0
        for pk in eligible:
            mid = pk["_match_id"]
            if mid in used_matches:
                continue
            mkt = pk["market"]
            if used_markets.get(mkt, 0) >= 2:
                continue
            new_combined = combined * pk["odds"]
            if new_combined > target_max + 2.0:
                break
            chosen.append(pk)
            used_matches.add(mid)
            used_markets[mkt] = used_markets.get(mkt, 0) + 1
            combined = new_combined
            if len(chosen) >= max_picks:
                break
        games = []
        for pk in chosen:
            p = pk["_pred"]
            game = _to_game(p)
            game["prediction"] = pk["prediction"]
            game["prediction_type"] = pk["market"]
            game["confidence"] = pk["confidence"]
            game["estimated_odds"] = pk["odds"]
            game["odds"] = pk["odds"]
            game["real_odds"] = pk["odds"]
            games.append(game)
        total = 1.0
        for g in games:
            total *= g["estimated_odds"]
        return games, round(total, 2)

    # All tiers use >70% confidence — higher tiers just stack MORE picks
    # ── 2 Odds: 3-4 safe picks ──
    two_odds_games, two_odds_total = _build_category(pick_pool, 3.5, 4)

    # ── 5 Odds: 5-7 safe picks ──
    five_odds_games, five_odds_total = _build_category(pick_pool, 8.0, 7)

    # ── 10 Odds: 8-10 safe picks ──
    ten_odds_games, ten_odds_total = _build_category(pick_pool, 15.0, 10)

    # ── Over 1.5: safest goal picks ──
    over_picks = []
    used_o = set()
    for p in day_preds:
        if p["match_id"] in used_o:
            continue
        o15 = p.get("goals", {}).get("over_1_5_prob", 0)
        if o15 >= 0.70:
            game = _to_game(p)
            game["prediction"] = "Over 1.5 Goals"
            game["prediction_type"] = "over_1_5"
            game["confidence"] = o15
            game["estimated_odds"] = round(1.0 / max(o15, 0.1), 2)
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
    five_ok = len(five_odds_games) >= 4 and five_odds_total >= 3.0
    ten_ok = len(ten_odds_games) >= 6 and ten_odds_total >= 5.0

    result = {
        "status": "success",
        "date": target_date,
        "source": "leagues",
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


def _all_picks(p: dict) -> list[dict]:
    """
    Return ALL viable picks for a match using the model's full output.

    Uses real bookmaker odds when available, estimated odds as fallback.
    Covers: match result, over/under 2.5, over 1.5, BTTS, double chance.
    """
    bo = p.get("best_odds", {})
    g = p.get("goals", {})
    probs = p.get("probabilities", {})
    candidates = []

    # Home/Away Win — use REAL bookmaker odds
    for key, odds_key in [("home_win", "home_win"), ("away_win", "away_win")]:
        prob = probs.get(key, 0)
        odds = bo.get(odds_key)
        if prob >= 0.60 and odds and odds >= 1.10:
            label = f"{p['home_team']} Win" if key == "home_win" else f"{p['away_team']} Win"
            candidates.append({"confidence": round(prob, 3), "odds": round(odds, 2), "prediction": label, "market": "match_result"})

    # Over 2.5 Goals — only when model is confident (>60%)
    o25 = g.get("over_2_5_prob", 0)
    o25_odds = bo.get("over_2_5")
    if o25 >= 0.60 and o25_odds and o25_odds >= 1.10:
        candidates.append({"confidence": round(o25, 3), "odds": round(o25_odds, 2), "prediction": "Over 2.5 Goals", "market": "goals"})

    # Under 2.5 Goals — only when model is confident (>60%)
    u25 = g.get("under_2_5_prob", 0)
    u25_odds = bo.get("under_2_5")
    if u25 >= 0.60 and u25_odds and u25_odds >= 1.10:
        candidates.append({"confidence": round(u25, 3), "odds": round(u25_odds, 2), "prediction": "Under 2.5 Goals", "market": "goals"})

    # Over 1.5 Goals — estimate odds from probability
    o15 = g.get("over_1_5_prob", 0)
    if o15 >= 0.70:
        est = round(1.0 / max(o15, 0.62), 2)
        if est >= 1.10:
            candidates.append({"confidence": round(o15, 3), "odds": est, "prediction": "Over 1.5 Goals", "market": "goals"})

    # BTTS Yes — only when genuinely confident
    btts = g.get("btts_prob", 0)
    if btts >= 0.60:
        est = round(1.0 / max(btts, 0.40), 2)
        candidates.append({"confidence": round(btts, 3), "odds": round(est, 2), "prediction": "Both Teams to Score", "market": "btts"})

    # BTTS No
    btts_no = 1.0 - btts if btts else 0
    if btts_no >= 0.60:
        est = round(1.0 / max(btts_no, 0.40), 2)
        candidates.append({"confidence": round(btts_no, 3), "odds": round(est, 2), "prediction": "BTTS No", "market": "btts"})

    # Double chance — fallback for genuinely tight matches
    hw = probs.get("home_win", 0)
    aw = probs.get("away_win", 0)
    dr = probs.get("draw", 0)
    home_or_draw = min(0.95, hw + dr)
    away_or_draw = min(0.95, aw + dr)
    if home_or_draw >= 0.75:
        est = round(1.0 / max(home_or_draw, 0.55), 2)
        candidates.append({"confidence": round(home_or_draw, 3), "odds": est, "prediction": f"{p['home_team']} or Draw", "market": "double_chance"})
    if away_or_draw >= 0.75:
        est = round(1.0 / max(away_or_draw, 0.55), 2)
        candidates.append({"confidence": round(away_or_draw, 3), "odds": est, "prediction": f"{p['away_team']} or Draw", "market": "double_chance"})

    return candidates


def _safest_pick(p: dict) -> dict | None:
    """Return the single highest-confidence pick for a match."""
    picks = _all_picks(p)
    if not picks:
        return None
    picks.sort(key=lambda x: x["confidence"], reverse=True)
    return picks[0]


TARGET_DAY_ODDS_MIN = 2.0
TARGET_DAY_ODDS_MAX = 3.0


def _select_rollover_picks(day_matches: list) -> list:
    """
    Select 4-5 safe picks for one rollover day that combine to 2.0–3.0 odds.

    Strategy: pick the best option per match, preferring markets with real
    bookmaker odds (match_result, over/under 2.5) over estimated-odds markets.
    Mix markets for variety — not all double_chance or all over 1.5.
    """
    match_candidates = []
    for m in day_matches:
        picks = _all_picks(m["pred"])
        if not picks:
            continue
        viable = [pk for pk in picks if pk["odds"] >= 1.10 and pk["confidence"] >= 0.70]
        if not viable:
            continue

        # Prefer match_result and BTTS over double_chance for variety.
        # Double_chance is a fallback — safe but boring and low-odds.
        MARKET_PREF = {"match_result": 1.3, "goals": 1.1, "btts": 1.2, "double_chance": 0.7}
        for pk in viable:
            mw = MARKET_PREF.get(pk["market"], 1.0)
            pk["_score"] = pk["confidence"] * pk["odds"] * mw

        viable.sort(key=lambda x: x["_score"], reverse=True)
        match_candidates.append({"pred": m["pred"], "pick": viable[0]})

    if not match_candidates:
        return []

    # Sort by confidence — safest first, but the per-match selection already
    # balanced confidence vs odds
    match_candidates.sort(key=lambda x: x["pick"]["confidence"], reverse=True)

    chosen = []
    combined = 1.0
    for mc in match_candidates:
        if combined >= TARGET_DAY_ODDS_MAX:
            break
        new_combined = combined * mc["pick"]["odds"]
        if new_combined > TARGET_DAY_ODDS_MAX + 0.5 and combined >= TARGET_DAY_ODDS_MIN:
            break
        chosen.append(mc)
        combined = new_combined
        if len(chosen) >= 4 and combined >= TARGET_DAY_ODDS_MIN:
            break
        if len(chosen) >= 6:
            break

    return chosen


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
        league_name = (p.get("data_quality") or {}).get("league") or "Football"
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
    - Each day slot = 4-5 SAFE picks (combined 2.0-3.0 odds per slot)
    - Pick = safest option per match across all markets
    - No match repeats across the entire chain
    - Days with 0 safe picks are skipped — chain pulls from next match day instead
    - All picks in a slot must hit for that slot to count
    """
    chain_path = DATA_DIR / "wc_rollover_chain.json"

    # Primary store: Postgres (survives Render redeploys).
    # Fallback: legacy JSON file on disk (still works locally / when DB unreachable).
    try:
        from leagues.rollover_db import load_chain as _db_load, append_day as _db_append, reset_chain as _db_reset
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

    # Void pending days stuck more than 2 days in the past — their matches
    # finished long ago; if the results checker couldn't resolve them by now
    # (name mismatch, source gap) they'd jam the chain forever otherwise.
    stale_cutoff = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    for day in chain.get("days", []):
        if day.get("status") == "pending" and day.get("date", "") < stale_cutoff:
            day["status"] = "void"
            logger.info(f"Voiding stale pending rollover day {day.get('date')}")
            if db_available:
                try:
                    from leagues.rollover_db import update_day_status as _db_update
                    _db_update(day["date"], "void")
                except Exception as e:
                    logger.warning(f"Could not persist void for {day.get('date')}: {e}")

    # Start a new chain if the current one is complete (all 10 days resolved)
    if len(chain.get("days", [])) >= 10:
        all_resolved = all(d.get("status") in ("won", "lost", "void") for d in chain["days"])
        if all_resolved:
            logger.info(f"Chain complete ({chain.get('start_date')}): all 10 days resolved — starting new chain")
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

    # Group upcoming predictions by date
    by_date: dict[str, list] = {}
    for p in upcoming:
        if not _all_picks(p):
            continue
        date = p["commence_time"][:10]
        by_date.setdefault(date, []).append({"pred": p})

    # Don't add days before the last chain date
    last_date = chain["days"][-1]["date"] if chain.get("days") else ""

    # Add new day slots up to 10 total
    needed = 10 - len(chain.get("days", []))

    for date in sorted(by_date.keys()):
        if needed <= 0:
            break
        if date <= last_date:
            continue

        # Select picks that combine to 2.0–3.0 daily odds
        chosen = _select_rollover_picks(by_date[date])

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
                "league": "Football",
                "date": pk.get("commence_time", ""),
                "prediction": pk.get("prediction", ""),
                "prediction_type": pk.get("market", "match_result"),
                "confidence": pk.get("confidence", 0.5),
                "estimated_odds": pk.get("odds"),
                "odds": pk.get("odds"),
                "home_team_logo": pk.get("home_team_logo"),
                "away_team_logo": pk.get("away_team_logo"),
                "risk_level": "low",
                "model_type": "leagues_safe",
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
