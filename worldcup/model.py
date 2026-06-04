"""
World Cup 2026 — Prediction Model

Combines:
1. Bookmaker implied probabilities (strongest signal — wisdom of markets)
2. WC 2022 team performance profiles (form, goals, defense)
3. World Cup-specific base rates (home advantage, goal rates)

For teams WITHOUT WC 2022 data: uses bookmaker odds only + WC average stats.
For teams WITH WC 2022 data: adjusts odds by ±15% based on form.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
DATA_DIR = Path(__file__).parent / "data"


def _load(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        return {} if filename.endswith("json") else []
    with open(path) as f:
        return json.load(f)


# Default profile for teams with no WC history
DEFAULT_PROFILE = {
    "win_rate": 0.33, "draw_rate": 0.33, "loss_rate": 0.33,
    "goals_scored_avg": 1.2, "goals_conceded_avg": 1.3,
    "goal_diff_avg": -0.1, "clean_sheet_rate": 0.2,
    "matches": 0,
}


def predict_match(
    home_team: str,
    away_team: str,
    home_profile: dict,
    away_profile: dict,
    implied_probs: dict,
    best_odds: dict,
    wc_stats: dict,
) -> dict:
    """
    Predict a single WC match.

    Weighting:
    - Bookmaker odds: 75% weight (they have massive data teams)
    - Team form: 15% weight (WC 2022 performance)
    - WC base rates: 10% weight (tournament-specific patterns)
    """

    # === 1. Bookmaker probabilities (75% weight) ===
    bk_home = implied_probs.get("home_win") or 0.33
    bk_draw = implied_probs.get("draw") or 0.28
    bk_away = implied_probs.get("away_win") or 0.33

    # Remove bookmaker margin (normalize)
    bk_total = bk_home + bk_draw + bk_away
    if bk_total > 0:
        bk_home /= bk_total
        bk_draw /= bk_total
        bk_away /= bk_total

    # === 2. Team form signal (15% weight) ===
    home_has_data = home_profile.get("matches", 0) > 0
    away_has_data = away_profile.get("matches", 0) > 0

    if home_has_data and away_has_data:
        # Both teams have WC data — use form differential
        form_home = home_profile["win_rate"]
        form_away = away_profile["win_rate"]
        form_draw = (home_profile["draw_rate"] + away_profile["draw_rate"]) / 2

        form_total = form_home + form_draw + form_away
        if form_total > 0:
            form_home /= form_total
            form_draw /= form_total
            form_away /= form_total
    else:
        # Use bookmaker odds as form proxy
        form_home = bk_home
        form_draw = bk_draw
        form_away = bk_away

    # === 3. WC base rates (10% weight) ===
    base_home = wc_stats.get("home_win_rate", 0.45)
    base_draw = wc_stats.get("draw_rate", 0.23)
    base_away = wc_stats.get("away_win_rate", 0.32)

    # === Weighted combination ===
    final_home = 0.75 * bk_home + 0.15 * form_home + 0.10 * base_home
    final_draw = 0.75 * bk_draw + 0.15 * form_draw + 0.10 * base_draw
    final_away = 0.75 * bk_away + 0.15 * form_away + 0.10 * base_away

    # Normalize
    total = final_home + final_draw + final_away
    final_home /= total
    final_draw /= total
    final_away /= total

    # === Goals prediction ===
    wc_avg_total = wc_stats.get("avg_goals_per_match", 2.69)
    wc_avg_home = wc_stats.get("avg_home_goals", 1.58)
    wc_avg_away = wc_stats.get("avg_away_goals", 1.11)

    home_attack = home_profile.get("goals_scored_avg", wc_avg_home)
    away_attack = away_profile.get("goals_scored_avg", wc_avg_away)
    home_defense = home_profile.get("goals_conceded_avg", wc_avg_away)
    away_defense = away_profile.get("goals_conceded_avg", wc_avg_home)

    # Expected goals — blend team data with WC averages
    exp_home = (home_attack + away_defense + wc_avg_home) / 3
    exp_away = (away_attack + home_defense + wc_avg_away) / 3
    exp_total = exp_home + exp_away

    # Over/Under from bookmakers (if available) or calculated
    over_2_5_prob = implied_probs.get("over_2_5")
    under_2_5_prob = implied_probs.get("under_2_5")
    if over_2_5_prob and under_2_5_prob:
        # Normalize bookmaker over/under
        ou_total = over_2_5_prob + under_2_5_prob
        over_2_5_prob /= ou_total
        under_2_5_prob /= ou_total
    else:
        # Estimate from expected goals (Poisson-ish)
        over_2_5_prob = min(0.85, max(0.15, 0.3 + (exp_total - 2.5) * 0.2))
        under_2_5_prob = 1 - over_2_5_prob

    # BTTS
    btts_prob = min(0.75, max(0.20,
        (1 - home_profile.get("clean_sheet_rate", 0.2)) *
        (1 - away_profile.get("clean_sheet_rate", 0.2)) * 0.7
    ))

    # Over 1.5 (for safer bets)
    over_1_5_prob = min(0.92, max(0.40, 0.5 + (exp_total - 1.5) * 0.25))

    # === Determine prediction ===
    probs = {"home_win": final_home, "draw": final_draw, "away_win": final_away}
    pred_key = max(probs, key=probs.get)
    confidence = probs[pred_key]

    pred_labels = {
        "home_win": f"{home_team} Win",
        "draw": "Draw",
        "away_win": f"{away_team} Win",
    }

    # === Value bets ===
    value_bets = []
    for key, label, odds_key in [
        ("home_win", f"{home_team} Win", "home_win"),
        ("away_win", f"{away_team} Win", "away_win"),
        ("draw", "Draw", "draw"),
    ]:
        odds = best_odds.get(odds_key)
        if odds and odds > 1:
            implied = 1.0 / odds
            our_prob = probs[key]
            edge = our_prob - implied
            ev = our_prob * odds - 1
            if edge > 0.02:  # At least 2% edge
                value_bets.append({
                    "bet": label,
                    "market": "match_result",
                    "odds": odds,
                    "our_prob": round(our_prob, 3),
                    "implied_prob": round(implied, 3),
                    "edge": round(edge, 3),
                    "expected_value": round(ev, 3),
                })

    # Over 2.5 value
    if best_odds.get("over_2_5"):
        odds = best_odds["over_2_5"]
        implied = 1.0 / odds
        edge = over_2_5_prob - implied
        if edge > 0.02:
            value_bets.append({
                "bet": "Over 2.5 Goals",
                "market": "totals",
                "odds": odds,
                "our_prob": round(over_2_5_prob, 3),
                "implied_prob": round(implied, 3),
                "edge": round(edge, 3),
                "expected_value": round(over_2_5_prob * odds - 1, 3),
            })

    value_bets.sort(key=lambda x: x["expected_value"], reverse=True)

    # === Risk level ===
    if confidence >= 0.50:
        risk = "low"
    elif confidence >= 0.38:
        risk = "medium"
    else:
        risk = "high"

    return {
        "prediction": pred_labels[pred_key],
        "prediction_key": pred_key,
        "confidence": round(confidence, 3),
        "risk_level": risk,
        "probabilities": {k: round(v, 3) for k, v in probs.items()},
        "goals": {
            "expected_home": round(exp_home, 2),
            "expected_away": round(exp_away, 2),
            "expected_total": round(exp_total, 2),
            "over_2_5_prob": round(over_2_5_prob, 3),
            "under_2_5_prob": round(under_2_5_prob, 3),
            "over_1_5_prob": round(over_1_5_prob, 3),
            "btts_prob": round(btts_prob, 3),
        },
        "best_odds": best_odds,
        "value_bets": value_bets,
        "data_quality": {
            "home_has_wc_data": home_has_data,
            "away_has_wc_data": away_has_data,
            "home_wc_matches": home_profile.get("matches", 0),
            "away_wc_matches": away_profile.get("matches", 0),
        },
    }


def generate_all_predictions() -> list:
    """Generate predictions for all 72 WC 2026 fixtures."""
    fixtures = _load("wc_fixtures.json")
    profiles = _load("wc_team_profiles.json")
    wc_stats = _load("wc_stats.json")
    team_ids = _load("wc_team_ids.json")

    if not fixtures:
        logger.error("No fixtures. Run fetch_data.py first.")
        return []

    if not wc_stats:
        # Fallback WC stats
        wc_stats = {
            "home_win_rate": 0.45, "draw_rate": 0.23, "away_win_rate": 0.32,
            "avg_goals_per_match": 2.69, "avg_home_goals": 1.58, "avg_away_goals": 1.11,
        }

    logger.info(f"Generating predictions for {len(fixtures)} fixtures...")
    logger.info(f"Team profiles available: {len(profiles)}")

    predictions = []
    for fx in fixtures:
        home = fx["home_team"]
        away = fx["away_team"]

        home_prof = profiles.get(home, DEFAULT_PROFILE)
        away_prof = profiles.get(away, DEFAULT_PROFILE)

        pred = predict_match(
            home_team=home,
            away_team=away,
            home_profile=home_prof,
            away_profile=away_prof,
            implied_probs=fx.get("implied_prob", {}),
            best_odds=fx.get("best_odds", {}),
            wc_stats=wc_stats,
        )

        # Add match info
        home_info = team_ids.get(home, {})
        away_info = team_ids.get(away, {})

        predictions.append({
            "match_id": fx["id"],
            "home_team": home,
            "away_team": away,
            "home_team_logo": home_info.get("logo"),
            "away_team_logo": away_info.get("logo"),
            "commence_time": fx["commence_time"],
            **pred,
        })

    # Save
    with open(DATA_DIR / "wc_predictions.json", "w") as f:
        json.dump(predictions, f, indent=2)

    # Stats
    high_conf = sum(1 for p in predictions if p["confidence"] >= 0.45)
    with_value = sum(1 for p in predictions if p["value_bets"])
    with_data = sum(1 for p in predictions if p["data_quality"]["home_has_wc_data"] and p["data_quality"]["away_has_wc_data"])

    logger.info(f"Predictions generated: {len(predictions)}")
    logger.info(f"High confidence (>45%): {high_conf}")
    logger.info(f"Matches with value bets: {with_value}")
    logger.info(f"Matches with full WC data: {with_data}")

    return predictions


if __name__ == "__main__":
    generate_all_predictions()
