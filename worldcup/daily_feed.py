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

    return {
        "fixture_id": hash(p.get("match_id", "")) % 1000000,
        "home_team": p.get("home_team", ""),
        "away_team": p.get("away_team", ""),
        "league": "FIFA World Cup 2026",
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
        "model_type": "worldcup_ensemble",
        "home_team_logo": p.get("home_team_logo"),
        "away_team_logo": p.get("away_team_logo"),
        "league_logo": "https://media.api-sports.io/football/leagues/1.png",
    }


def build_daily_accumulators() -> dict:
    """
    Build accumulator categories from WC predictions for today/next match day.

    Returns data in the exact format the frontend expects from /accumulators/today.
    """
    predictions = _load("wc_predictions.json")
    if not predictions:
        return None

    today = datetime.now().strftime("%Y-%m-%d")

    # Find next match day
    match_dates = sorted(set(p["commence_time"][:10] for p in predictions))
    next_dates = [d for d in match_dates if d >= today]
    target_date = next_dates[0] if next_dates else (match_dates[-1] if match_dates else today)

    # Get predictions for target date
    day_preds = [p for p in predictions if p["commence_time"].startswith(target_date)]

    # If no matches on target date, use next available
    if not day_preds and next_dates:
        for nd in next_dates:
            day_preds = [p for p in predictions if p["commence_time"].startswith(nd)]
            if day_preds:
                target_date = nd
                break

    if not day_preds:
        day_preds = [p for p in predictions if p["commence_time"][:10] >= today][:15]

    # Always include enough matches to build good accumulators
    # Pull from next several days until we have at least 8 matches
    all_upcoming = [p for p in predictions if p["commence_time"][:10] >= today]
    if len(day_preds) < 8:
        for p in all_upcoming:
            if p not in day_preds:
                day_preds.append(p)
            if len(day_preds) >= 12:
                break

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

    # ── Rollover: 1 pick per day at 2-3 odds, 10-day chain ──
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

    result = {
        "status": "success",
        "date": target_date,
        "source": "worldcup",
        "accumulators": {
            "2_odds": mk_cat(two_odds_games, two_odds_total, "Low"),
            "5_odds": mk_cat(five_odds_games, five_odds_total, "Medium"),
            "10_odds": mk_cat(ten_odds_games, ten_odds_total, "High"),
            "over_1_5": mk_cat(over_picks, over_total, "Very Safe"),
            "rollover": rollover,
        },
    }

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

    if chain_path.exists():
        with open(chain_path) as f:
            chain = json.load(f)
    else:
        chain = {"start_date": today, "days": [], "status": "active"}

    # Reset chain if start_date is too old
    if chain.get("start_date"):
        try:
            start = datetime.strptime(chain["start_date"], "%Y-%m-%d")
            if (datetime.now() - start).days > 30:
                chain = {"start_date": today, "days": [], "status": "active"}
        except Exception:
            chain = {"start_date": today, "days": [], "status": "active"}

    # Detect old chain schema (with 'prediction'/'odds' at day level instead of 'picks') and reset
    if chain.get("days") and "picks" not in chain["days"][0]:
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

        chain["days"].append({
            "day_number": len(chain["days"]) + 1,
            "date": date,
            "picks": picks_data,
            "combined_odds": round(combined, 2),
            "avg_confidence": round(sum(pk["confidence"] for pk in picks_data) / len(picks_data), 3),
            "status": "pending",
        })
        needed -= 1
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
