"""Retrospective NBA score model challenger: transparent chronological selection.

Six fixed coherent score configurations are compared on 2025 *development*
only. The 2026 cohort is scored after configuration selection and is NOT a
genuinely untouched external study (2026 already studied in earlier reports).
No previously saved model/prediction/ledger is ever changed or published.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from itertools import groupby

from basketball.research_opening_score import (
    _corrected, _history, candidates as original_candidates,
    _metrics as metrics, TARGETS
)

VERSION = "nba-opening-score-challenger-development-v1"
# Predeclared hypotheses: no hyperparameter tuning on the 2026 evaluation
# season or genuine 2027 results.
CONFIGS = (
    ("v1_original", 12, 1.5),
    ("recent_heavy", 4, 1.5),
    ("prior_heavy", 24, 1.5),
    ("prior_extra_heavy", 48, 1.5),
    ("zero_added_home_edge", 12, 0.0),
    ("larger_home_edge", 12, 3.0),
)
TARGETS_TO_MEASURE = ("total", "home_margin", "home_points", "away_points")


def _all_variants(games):
    """Use exactly the eligibility cohort and earlier-only state of v1.

    Build every hypothesis on the same completed fixtures; never use target
    date results for its current-season features, including same-date finals.
    """
    source = _corrected(games)
    base = original_candidates(games, historical=True)
    lookup = {(r["season"], r["game_id"]): r for r in base}
    previous, league = _history(source)
    current = defaultdict(lambda: [0.0, 0.0, 0])
    alternative = []
    ordered = sorted(source, key=lambda g:
                     (int(g["season"]), g["date"], str(g["game_id"])))
    for (_, _), part in groupby(
        ordered, key=lambda g: (int(g["season"]), g["date"])
    ):
        day = list(part)
        for g in day:
            key = (int(g["season"]), str(g["game_id"]))
            reference = lookup.get(key)
            if reference is None:
                continue
            home_id, away_id = str(g["home_id"]), str(g["away_id"])
            hp, ap = previous[(g["season"] - 1, home_id)], previous[
                (g["season"] - 1, away_id)]
            hc, ac = current[(g["season"], home_id)], current[
                (g["season"], away_id)]
            if (hc[2] != reference["current_home_games"] or
                ac[2] != reference["current_away_games"]):
                raise ValueError("Challenger same-day leakage or cohort mismatch")
            values = {}
            for name, pseudo, edge in CONFIGS:
                def avg(prev, recent):
                    return ((pseudo * prev[0] / prev[2] + recent[0]) /
                            (pseudo + recent[2]),
                            (pseudo * prev[1] / prev[2] + recent[1]) /
                            (pseudo + recent[2]))
                hf, ha = avg(hp, hc)
                af, aa = avg(ap, ac)
                home_pts = (hf + aa) / 2 + edge
                away_pts = (af + ha) / 2 - edge
                values[name] = {
                    "predicted_total": home_pts + away_pts,
                    "predicted_home_margin": home_pts - away_pts,
                    "predicted_home_points": home_pts,
                    "predicted_away_points": away_pts,
                }
            # Identical real outcome/cohort, not an independent feature join.
            alternative.append({**reference, "candidate_variants": values})
        for g in day:
            if g["status"] != "final" or g["postseason"]:
                continue
            season, h, a = g["season"], str(g["home_id"]), str(g["away_id"])
            hs, av = g["home_score"], g["away_score"]
            current[(season, h)][0] += hs
            current[(season, h)][1] += av
            current[(season, h)][2] += 1
            current[(season, a)][0] += av
            current[(season, a)][1] += hs
            current[(season, a)][2] += 1
    if len(alternative) != len(base):
        raise ValueError("Challenger lost original opening-week matches")
    return sorted(alternative, key=lambda r: (r["start_utc"], r["game_id"]))


def _with_candidate(cohort, version):
    return [{**row, **row["candidate_variants"][version]} for row in cohort]


def _objective(cohort, version):
    if not cohort:
        raise ValueError("No historical development cohort to score")
    scored = metrics(_with_candidate(cohort, version))
    ratios = []
    for target in TARGETS_TO_MEASURE:
        measure = scored["targets"][target]
        baseline = measure["baseline_mae"]
        if baseline is None or baseline <= 0:
            raise ValueError("Invalid NBA baseline on development cohort")
        ratios.append(measure["candidate_mae"] / baseline)
    return round(sum(ratios) / len(ratios), 8)


def _paired_uncertainty(cohort, target, *, seed=1109, draws=1200):
    """Calendar-day clustered bootstrap paired MAE improvement interval.

    Each resample includes the same source-day games for candidate and
    baseline. A CI straddling zero is inconclusive, never a promotion gate.
    """
    spec = next((v for v in TARGETS if v[0] == target), None)
    if spec is None:
        raise ValueError("Invalid target")
    _, pred, baseline, actual = spec
    days = defaultdict(list)
    for r in cohort:
        days[r["date"]].append(abs(r[baseline] - r[actual]) -
                               abs(r[pred] - r[actual]))
    if len(days) < 4:
        return {"low": None, "high": None, "calendar_days": len(days),
                "status": "too_few_independent_dates"}
    groups = list(days.values())
    rng = random.Random(seed)
    sampled = []
    for _ in range(draws):
        draw = [groups[rng.randrange(len(groups))]
                for _ in range(len(groups))]
        flattened = [v for batch in draw for v in batch]
        sampled.append(sum(flattened) / len(flattened))
    sampled.sort()
    low = sampled[int((draws-1)*.025)]
    high = sampled[int((draws-1)*.975)]
    return {"low": round(low, 4), "high": round(high, 4),
            "calendar_days": len(days), "status":
                "positive_only_if_low_gt_zero" if low > 0
                else "interval_includes_or_below_zero",
            "method": "paired_calendar_day_bootstrap",
            "draws": draws}


def challenge(games):
    all_rows = _all_variants(games)
    dev = [r for r in all_rows if r["season"] == 2025]
    test = [r for r in all_rows if r["season"] == 2026]
    if not dev:
        return {
            "status": "insufficient_2025_development_rows",
            "research_only": True, "no_writes": True,
            "development_games": 0, "retrospective_2026_games": len(test),
            "model_promotion_approved": False,
        }
    ranks = sorted(((_objective(dev, name), name)
                    for name, _, _ in CONFIGS),
                   key=lambda result: (result[0], result[1]))
    winner = ranks[0][1]
    dev_winner = metrics(_with_candidate(dev, winner))
    old_dev = metrics(_with_candidate(dev, "v1_original"))
    test_winner = metrics(_with_candidate(test, winner))
    old_test = metrics(_with_candidate(test, "v1_original"))
    enriched = _with_candidate(test, winner)
    intervals = {target: _paired_uncertainty(enriched, target)
                 for target in TARGETS_TO_MEASURE}
    target_gates = {}
    for target in TARGETS_TO_MEASURE:
        selected = test_winner["targets"][target]
        original = old_test["targets"][target]
        target_gates[target] = {
            "better_than_baseline": (
                selected["paired_mae_improvement"] > 0
                if test else None),
            "at_least_as_good_as_original": (
                selected["candidate_mae"] <= original["candidate_mae"]
                if test else None),
            "positive_bootstrap_interval": (
                intervals[target]["low"] > 0
                if intervals[target]["low"] is not None else None),
        }
    return {
        "status": "retrospective_comparison_only",
        "version": VERSION,
        "hypotheses_predeclared": len(CONFIGS),
        "configuration_selected_using_2025_only": winner,
        "config_specification": next({
            "season_current_pseudogames": p, "home_advantage_points": edge,
        } for name, p, edge in CONFIGS if name == winner),
        "selection_objective": (
            "mean of 2025 candidate MAE / 2025 baseline MAE "
            "for 4 coherent score targets"),
        "development_2025": {
            "games": len(dev),
            "selected": dev_winner,
            "original": old_dev,
            "ranks_2025_only": [
                {"candidate": name, "objective": obj}
                for obj, name in ranks],
        },
        "retrospective_2026": {
            "games": len(test),
            "selected": test_winner, "original": old_test,
            "paired_improvement_uncertainty": intervals,
            "provisional_target_gates": target_gates,
            "not_untouched_across_prior_project_work": True,
            "sample_size_is_small": len(test) < 100,
        },
        "strict_earlier_provider_date_features": True,
        "prior_season_nonstandings_cup_game_excluded_in_memory": True,
        "forecast_archive_or_model_changed": False,
        "training_on_2027_outcomes": False,
        "genuine_forward_2027_games_used_for_selection": 0,
        "model_promotion_approved": False,
        "new_predictions_recorded": 0,
        "betting_lines_and_prices_available": False,
        "research_only": True,
        "no_writes": True,
    }
