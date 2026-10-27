"""Read-only, pre-registered NBA paper-model acceptance thresholds.

Sample size never counts multiple models as multiple distinct game outcomes.
No betting edge, public promotion, new training or data mutation.
"""
from __future__ import annotations

import math
from basketball.research_private_bundle import inspect_bundle

MIN_PROSPECTIVE_GAMES = 150
MAX_ECE = 0.08


def _round_average(items):
    return round(sum(items) / len(items), 6) if items else None


def _pairs(bundle, kind):
    saved = bundle["records"]
    done = {str(s["game_id"]) for s in saved[kind + "_finals"]}
    finals = {str(g["game_id"]): g for g in bundle["fixtures"]
              if g["status"] == "final"}
    return [(f, finals[str(f["game_id"])]) for f in saved[kind]
            if str(f["game_id"]) in done and str(f["game_id"]) in finals]


def grade_models(bundle):
    """Grade immutable pregame forecasts against independently verified finals."""
    inspect_bundle(bundle)
    money, score, advanced = (_pairs(bundle, kind) for kind in
                              ("moneyline", "opening_score", "early_advanced"))
    model_brier, base_brier, hits, bins = [], [], 0, [[0, 0., 0.] for _ in range(5)]
    for f, game in money:
        p = f["probability_home_win"]
        base = f["previous_season_home_baseline"]
        if any(type(x) not in (int, float) or not math.isfinite(x)
               or x < 0 or x > 1 for x in (p, base)):
            raise ValueError("NBA_UNSAFE_PROBABILITY_IN_ARCHIVE")
        actual = float(game["home_score"] > game["away_score"])
        model_brier.append((p - actual) ** 2)
        base_brier.append((base - actual) ** 2)
        hits += int((p >= .5) == (actual == 1))
        cell = bins[min(4, int(p * 5))]
        cell[0] += 1
        cell[1] += p
        cell[2] += actual
    ece = None
    if money:
        ece = round(sum(abs(c[1]/c[0]-c[2]/c[0]) * c[0]/len(money)
                        for c in bins if c[0]), 6)
    orig_mae, league_mae = [], []
    for f, game in score:
        total = game["home_score"] + game["away_score"]
        orig_mae.append(abs(f["predicted_total"] - total))
        league_mae.append(abs(f["league_baseline_total"] - total))
    adv_mae, paired_orig_mae = [], []
    for f, game in advanced:
        total = game["home_score"] + game["away_score"]
        adv_mae.append(abs(f["predicted_total"] - total))
        paired_orig_mae.append(abs(f["original_predicted_total"] - total))
    brier_gain = (_round_average(base_brier) - _round_average(model_brier)
                  if money else None)
    advanced_gain = (_round_average(paired_orig_mae) - _round_average(adv_mae)
                     if advanced else None)
    money_accepted = (len(money) >= MIN_PROSPECTIVE_GAMES
                      and brier_gain is not None and brier_gain > 0
                      and ece is not None and ece <= MAX_ECE)
    advanced_accepted = (len(advanced) >= MIN_PROSPECTIVE_GAMES
                         and advanced_gain is not None and advanced_gain > 0)
    return {
        "status": "research_only_evidence_gates",
        "research_only": True, "not_bookable": True,
        "public_predictions_enabled": False,
        "minimum_distinct_evaluations": MIN_PROSPECTIVE_GAMES,
        "moneyline": {
            "settled_games": len(money),
            "accuracy": round(hits / len(money), 6) if money else None,
            "brier": _round_average(model_brier),
            "baseline_brier": _round_average(base_brier),
            "brier_gain": round(brier_gain, 6) if brier_gain is not None else None,
            "calibration_ece": ece,
            "accepted": money_accepted,
        },
        "original_score": {
            "settled_games": len(score), "total_mae": _round_average(orig_mae),
            "league_baseline_mae": _round_average(league_mae),
        },
        "advanced_score": {
            "settled_games": len(advanced),
            "total_mae": _round_average(adv_mae),
            "original_mae_same_games": _round_average(paired_orig_mae),
            "paired_mae_gain": round(advanced_gain, 6)
                               if advanced_gain is not None else None,
            "accepted": advanced_accepted,
        },
        "release_blockers": [
            reason for reason, passed in (
                ("moneyline_out_of_sample_gate", money_accepted),
                ("advanced_score_gate", advanced_accepted),
                ("closing_line_market_gate", False),
                ("verified_operations_and_manual_approval", False),
            ) if not passed
        ],
    }
