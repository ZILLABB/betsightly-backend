"""NBA scoring-level regime challenger: chronological and read-only.

Historical source-derived current-season league scoring cannot use any final
from the predicted game or from the same provider date. Select a fixed
parameter using 2025 development data; report 2026 *retrospectively* only.
This investigation was inspired by already observed 2026 underprojection:
the 2026 comparison must NEVER be represented as an untouched holdout.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import groupby

from basketball.research_opening_score import (
    _corrected, _history, candidates as original_candidates, _metrics
)
from basketball.research_score_challenger import _paired_uncertainty

VERSION = "nba-opening-score-regime-diagnostic-v1"
CONFIGS = (
    ("original_unchanged", None),
    ("pace_fast", 20),
    ("pace_moderate", 60),
    ("pace_slow", 120),
    ("pace_very_slow", 240),
)
MIN_LEAGUE_FINALS = 5
MAX_ABSOLUTE_ADJUSTMENT = 12.0


def _league_adjustment(prior_mean, earlier_current_sum,
                       earlier_current_count, pseudo):
    """Shrink current league-average points to last-year league average."""
    if pseudo is None or earlier_current_count < MIN_LEAGUE_FINALS:
        return 0.0
    change = (earlier_current_sum / earlier_current_count - prior_mean)
    value = change * earlier_current_count / (
        earlier_current_count + pseudo)
    return max(-MAX_ABSOLUTE_ADJUSTMENT,
               min(MAX_ABSOLUTE_ADJUSTMENT, value))


def historical_candidates(games):
    """Same frozen opening-week evaluation cohort; no target-date leakage."""
    vetted = _corrected(games)
    original = original_candidates(games, historical=True)
    lookup = {(int(r["season"]), str(r["game_id"])): r for r in original}
    _, season_history = _history(vetted)
    earlier = defaultdict(lambda: [0.0, 0])
    output = []
    ordered = sorted(vetted, key=lambda g: (
        int(g["season"]), g["date"], str(g["game_id"])))
    for (season, _), group in groupby(
        ordered, key=lambda g: (int(g["season"]), g["date"])
    ):
        day = list(group)
        last_year = season_history[season-1]
        prior_mean = (
            (last_year[0]+last_year[1])/last_year[2]
            if last_year[2] > 0 else None)
        before_sum, before_count = earlier[season]
        for game in day:
            original_row = lookup.get((season, str(game["game_id"])))
            if original_row is None:
                continue
            if prior_mean is None or last_year[2] < 200:
                raise ValueError("Insufficient historical NBA pace baseline")
            forecast_variants = {}
            for name, pseudo in CONFIGS:
                adjustment = _league_adjustment(
                    prior_mean, before_sum, before_count, pseudo)
                home = original_row["predicted_home_points"] + adjustment/2
                away = original_row["predicted_away_points"] + adjustment/2
                forecast_variants[name] = {
                    "predicted_home_points": home,
                    "predicted_away_points": away,
                    "predicted_total": home+away,
                    "predicted_home_margin": home-away,
                    "pace_adjustment": adjustment,
                }
            output.append({
                **original_row,
                "earlier_season_league_finals": before_count,
                "season_start_prior_mean_total": round(prior_mean, 5),
                "regime_variants": forecast_variants,
            })
        # Crucial: games of the predicted date cannot influence ANY
        # pregame forecast issued for that same date.
        for game in day:
            if game["status"] == "final" and not game["postseason"]:
                scores = (game["home_score"], game["away_score"])
                if not all(isinstance(s, int) and not isinstance(s, bool)
                           for s in scores):
                    raise ValueError("Invalid earlier verified score")
                earlier[season][0] += sum(scores)
                earlier[season][1] += 1
    if len(output) != len(original):
        raise ValueError("Regime challenger lost the matched score cohort")
    return sorted(output, key=lambda r: (r["start_utc"], r["game_id"]))


def _as_variant(cohort, name):
    return [{**r, **r["regime_variants"][name]} for r in cohort]


def _selection_mae(cohort, name):
    return _metrics(_as_variant(cohort, name))["targets"]["total"][
        "candidate_mae"]


def examine(games):
    rows = historical_candidates(games)
    dev = [r for r in rows if r["season"] == 2025]
    retrospective = [r for r in rows if r["season"] == 2026]
    if len(dev) < 30:
        return {
            "status": "insufficient_development_cohort",
            "development_games": len(dev),
            "retrospective_games": len(retrospective),
            "no_writes": True, "research_only": True,
            "model_promotion_approved": False,
        }
    ranks = sorted(
        ((mae, name) for name, _ in CONFIGS
         for mae in [_selection_mae(dev, name)]),
        key=lambda row: (row[0], row[1]))
    selected = ranks[0][1]
    selected_rows = _as_variant(retrospective, selected)
    base_rows = _as_variant(retrospective, "original_unchanged")
    chosen = _metrics(selected_rows)
    base = _metrics(base_rows)
    intervals = {
        target: _paired_uncertainty(selected_rows, target)
        for target in ("total", "home_margin", "home_points", "away_points")
    }
    improvement = chosen["targets"]["total"]["paired_mae_improvement"]
    old_improvement = base["targets"]["total"]["paired_mae_improvement"]
    return {
        "status": "retrospective_comparison_only",
        "version": VERSION,
        "hypotheses": len(CONFIGS),
        "selected_from": "2025 development only (total MAE)",
        "selected": selected,
        "earlier_league_finals_required": MIN_LEAGUE_FINALS,
        "fixed_absolute_adjustment_cap_points": MAX_ABSOLUTE_ADJUSTMENT,
        "development_2025": {
            "games": len(dev),
            "rankings": [
                {"configuration": name, "total_mae": mae}
                for mae, name in ranks
            ],
            "selected": _metrics(_as_variant(dev, selected)),
            "original": _metrics(_as_variant(dev, "original_unchanged")),
        },
        "retrospective_2026": {
            "games": len(retrospective),
            "selected": chosen, "original": base,
            "selected_paired_uncertainty": intervals,
            "beats_baseline_on_total": (
                improvement > 0 if improvement is not None else None),
            "beats_original_on_total": (
                chosen["targets"]["total"]["candidate_mae"] <
                base["targets"]["total"]["candidate_mae"]
                if retrospective else None),
            "positive_total_uncertainty_interval": (
                intervals["total"]["low"] > 0
                if intervals["total"]["low"] is not None else None),
            "total_paired_improvement_vs_baseline": improvement,
            "original_total_paired_improvement_vs_baseline": old_improvement,
            "2026_diagnosis_informed_choice_of_experiment": True,
            "not_an_untouched_validation_cohort": True,
            "sample_size_small": len(retrospective) < 100,
        },
        "strict_earlier_date_current_season_league_data": True,
        "nonstandings_cup_final_excluded_from_features_only": True,
        "genuine_2027_forward_finals_used": 0,
        "bookmaker_lines_or_odds_validated": False,
        "no_saved_forecasts_rewritten": True,
        "original_model_unchanged": True,
        "model_promotion_approved": False,
        "research_only": True,
        "no_writes": True,
    }
