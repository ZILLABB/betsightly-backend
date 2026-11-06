"""Exploratory paired, date-clustered NBA Wave 2 paper diagnostics.

Consumes ONLY Wave 2 rows after research_wave2_report validates the SHA-256
pregame archive, fixture identity and independently verified settlement.
No model fitting, thresholds, odds, bet issuance, or writes.
"""
from __future__ import annotations

import math
import random
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date
from pathlib import Path

MIN_REVIEW = 100
MIN_INTERVAL_GAMES = 20
MIN_INTERVAL_DATES = 3
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261106
METRICS = (
    "moneyline_brier", "moneyline_log_loss", "moneyline_accuracy",
    "total_points_mae", "home_margin_mae",
)


def _round(x):
    return round(x, 6) if x is not None else None


def _mean(values):
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _logloss(p, y):
    p = min(1 - 1e-12, max(1e-12, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _paired_values(row, home_score, away_score):
    y = int(home_score > away_score)
    candidate = row["candidate_home_win_probability"]
    v1 = row["matched_v1_home_win_probability"]
    deltas = {
        "moneyline_brier": (v1-y)**2 - (candidate-y)**2,
        "moneyline_log_loss": _logloss(v1, y) - _logloss(candidate, y),
        "moneyline_accuracy": (
            int((candidate >= 0.5) == bool(y)) -
            int((v1 >= 0.5) == bool(y))
        ),
    }
    for target, actual in (
        ("total_points", home_score + away_score),
        ("home_margin", home_score - away_score),
    ):
        c, b = row.get(f"candidate_{target}"), row.get(f"matched_v1_{target}")
        deltas[f"{target}_mae"] = (
            abs(b - actual) - abs(c - actual)
            if c is not None and b is not None else None
        )
    return deltas


def _quantile(sorted_values, fraction):
    position = (len(sorted_values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return sorted_values[low] + (position-low) * (
        sorted_values[high] - sorted_values[low])


def paired_uncertainty(scored):
    """Resample *dates*, keeping all games on one calendar date together.

    Percentile intervals are exploratory: dates and fixtures are not
    independent trials; intervals do not prove generalization or an edge.
    A positive improvement means candidate beats matched reduced-feature V1.
    """
    groups = defaultdict(list)
    for row, home, away in scored:
        groups[row["fixture_date"]].append(_paired_values(row, home, away))
    dates = sorted(groups)
    n = len(scored)
    ready = n >= MIN_INTERVAL_GAMES and len(dates) >= MIN_INTERVAL_DATES
    rng = random.Random(BOOTSTRAP_SEED)
    draws = {metric: [] for metric in METRICS}
    if ready:
        for _ in range(BOOTSTRAP_DRAWS):
            sampled = [item for _day in range(len(dates))
                       for item in groups[dates[rng.randrange(len(dates))]]]
            for metric in METRICS:
                avg = _mean([item[metric] for item in sampled])
                if avg is not None:
                    draws[metric].append(avg)
    all_observations = [item for day in dates for item in groups[day]]
    output = {}
    for metric in METRICS:
        values = [obs[metric] for obs in all_observations
                  if obs[metric] is not None]
        boot = sorted(draws[metric])
        has_interval = bool(boot) and len(values) >= MIN_INTERVAL_GAMES
        output[metric] = {
            "paired_games": len(values),
            "candidate_improvement": _round(_mean(values)),
            "ci95_lower": _round(_quantile(boot, 0.025)) if has_interval else None,
            "ci95_upper": _round(_quantile(boot, 0.975)) if has_interval else None,
            "interval_excludes_zero": (
                boot and (_quantile(boot, 0.025) > 0 or
                          _quantile(boot, 0.975) < 0)
            ) if has_interval else None,
            "exploratory_only": True,
        }
    return {
        "method": "paired_calendar_date_cluster_bootstrap_percentile",
        "seed": BOOTSTRAP_SEED,
        "draws": BOOTSTRAP_DRAWS if ready else 0,
        "distinct_game_dates": len(dates),
        "minimum_games_for_interval": MIN_INTERVAL_GAMES,
        "minimum_dates_for_interval": MIN_INTERVAL_DATES,
        "interval_status": "exploratory" if ready else "insufficient_date_clusters_or_games",
        "positive_delta_definition": (
            "V1 loss minus candidate loss for Brier/log loss/MAE; "
            "candidate correct minus V1 correct for accuracy"
        ),
        "comparisons": output,
        "not_an_edge_or_significance_test": True,
        "note": (
            "Games on the same date are resampled together; calendar dates "
            "can still be correlated. Few dates make intervals unstable. "
            "Do not use these intervals to select, tune, publish or bet."
        ),
    }


def _model_errors(scored, model):
    result = {}
    for target in ("total_points", "home_margin"):
        signed = []
        for row, home, away in scored:
            prediction = row.get(f"{model}_{target}")
            if prediction is not None:
                actual = home + away if target == "total_points" else home - away
                signed.append(prediction - actual)
        result[target] = {
            "games": len(signed),
            "mae": _round(_mean([abs(x) for x in signed])),
            "bias": _round(_mean(signed)),
            "overestimates": sum(x > 0 for x in signed),
            "underestimates": sum(x < 0 for x in signed),
        }
    return result


def bias_and_segments(scored):
    """Only descriptive groups. Postgame strata are never predictive filters."""
    if not scored:
        return {
            "segments": {}, "candidate_error_examples": [],
            "status": "awaiting_verified_finals",
            "no_feature_causality_inferred": True,
        }
    first_day = min(date.fromisoformat(row["fixture_date"])
                    for row, _, _ in scored)
    groups = defaultdict(lambda: defaultdict(list))
    for row, home, away in scored:
        p = row["candidate_home_win_probability"]
        winner_conf = max(p, 1 - p)
        actual_total = home + away
        days_since_first = (date.fromisoformat(row["fixture_date"]) -
                            first_day).days
        categories = {
            "forecast_favorite": ("home" if p > .5 else
                                  "away" if p < .5 else "tied_50_50"),
            "forecast_confidence": "70pct_plus" if winner_conf >= .7 else "below_70pct",
            "predicted_total_band": (
                "230_plus" if row.get("candidate_total_points") is not None and
                row["candidate_total_points"] >= 230 else "below_230_or_missing"),
            "actual_total_band_postgame": (
                "230_plus" if actual_total >= 230 else "below_230"),
            "actual_margin_postgame": (
                "close_5_or_less" if abs(home-away) <= 5 else "over_5"),
            "observed_period": (
                "first_14_observed_days" if days_since_first < 14
                else "later_observed_days"),
        }
        for group, name in categories.items():
            groups[group][name].append((row, home, away))
    segments = {}
    for group, buckets in sorted(groups.items()):
        segments[group] = {}
        for label, entries in sorted(buckets.items()):
            deltas = [_paired_values(r, h, a) for r, h, a in entries]
            segments[group][label] = {
                "games": len(entries),
                "small_sample": len(entries) < 20,
                "candidate": _model_errors(entries, "candidate"),
                "matched_v1": _model_errors(entries, "matched_v1"),
                "candidate_improvement": {
                    m: _round(_mean([item[m] for item in deltas]))
                    for m in METRICS
                },
            }
    worst = []
    for row, home, away in scored:
        for target, actual in (
            ("total_points", home + away), ("home_margin", home - away),
        ):
            predicted = row.get(f"candidate_{target}")
            baseline = row.get(f"matched_v1_{target}")
            if predicted is None:
                continue
            worst.append({
                "game_id": str(row["game_id"]),
                "fixture_date": row["fixture_date"],
                "target": target,
                "actual": actual,
                "candidate": predicted,
                "candidate_signed_error": _round(predicted-actual),
                "matched_v1": baseline,
                "matched_v1_signed_error": (
                    _round(baseline-actual) if baseline is not None else None
                ),
                "absolute_error": abs(predicted-actual),
            })
    worst.sort(key=lambda r: (-r["absolute_error"], r["fixture_date"],
                              r["game_id"], r["target"]))
    for row in worst:
        row.pop("absolute_error")
    return {
        "status": "descriptive_only",
        "segments": segments,
        "candidate_error_examples": worst[:10],
        "model_bias": {
            "candidate": _model_errors(scored, "candidate"),
            "matched_v1": _model_errors(scored, "matched_v1"),
        },
        "no_feature_causality_inferred": True,
        "postgame_segments_not_available_as_pregame_filters": True,
        "first_observed_date": first_day.isoformat(),
        "interpretation": (
            "Observed game outcomes and scores are used only to investigate "
            "past errors. No archived pace, injuries, opponent-strength or "
            "rest explanatory features are inferred from aggregate errors."
        ),
    }


def archived_original_v1_comparison(root, scored):
    """Compare original *saved* V1 paper predictions only on exact same finals.

    Never re-run a current V1 model on completed games. Require complete
    hash/timestamp checks from the original read-only prospective reader.
    """
    db_path = Path(root) / "nba_paper.sqlite"
    base = {
        "original_v1_model_version": "nba-moneyline-offline-v1",
        "comparison_source": "independently_saved_main_v1_sqlite_forecast",
        "source_path": str(db_path.resolve()),
        "research_only": True, "no_writes": True,
        "no_promotion_or_betting_edge": True,
        "model_weights_frozen_not_verified_by_this_comparison": True,
    }
    if not db_path.is_file():
        return {**base, "status": "main_v1_ledger_missing",
                "matched_games": 0}
    try:
        from basketball.research_prospective import _read_cohort, _utc
        uri = db_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            all_rows, errors = _read_cohort(db)
    except (sqlite3.Error, ValueError, OSError, TypeError, KeyError) as exc:
        return {**base, "status": "main_v1_ledger_unreadable",
                "reason": type(exc).__name__, "matched_games": 0}
    if errors:
        return {**base, "status": "main_v1_integrity_failed",
                "rejected_forecasts": len(errors), "matched_games": 0}
    cohort = {
        str(row["game_id"]): row for row in all_rows
        if row["model_version"] == "nba-moneyline-offline-v1"
        and row["recorded_at"] is not None
    }
    matched, mismatched = [], []
    for row, home, away in scored:
        original = cohort.get(str(row["game_id"]))
        if original is None:
            continue
        if (original["fixture_date"] != row["fixture_date"]
            or str(original["home_team_id"]) != str(row["home_id"])
            or str(original["away_team_id"]) != str(row["away_id"])
            or _utc(original["start_utc"]) != _utc(row["start_utc"])
            or (original["home_score"], original["away_score"]) != (home, away)):
            mismatched.append(str(row["game_id"]))
        else:
            matched.append((row, home, away, original))
    if mismatched:
        return {**base, "status": "exact_game_identity_or_score_conflict",
                "mismatch_count": len(mismatched),
                "mismatch_game_ids_sample": mismatched[:10],
                "matched_games": 0, "metrics_withheld": True}
    if not matched:
        return {**base, "status": "no_exact_settled_v1_pairs",
                "matched_games": 0,
                "main_v1_settled_records": len(cohort)}
    predictions = {
        "advanced_candidate": lambda shadow, original: (
            shadow["candidate_home_win_probability"]),
        "matched_reduced_feature_v1": lambda shadow, original: (
            shadow["matched_v1_home_win_probability"]),
        "original_main_v1_archive": lambda shadow, original: (
            float(original["home_win_probability"])),
    }
    metrics = {}
    for label, accessor in predictions.items():
        probs = [(accessor(shadow, original), int(home > away))
                 for shadow, home, away, original in matched]
        metrics[label] = {
            "accuracy": _round(_mean([
                int((p >= .5) == bool(y)) for p, y in probs])),
            "brier": _round(_mean([(p-y)**2 for p, y in probs])),
            "log_loss": _round(_mean([_logloss(p, y) for p, y in probs])),
        }
    score_metrics = {}
    for target, actual_fn in (
        ("total_points", lambda h, a: h+a),
        ("home_margin", lambda h, a: h-a),
    ):
        score_metrics[target] = {}
        for label, accessor in (
            ("advanced_candidate",
             lambda shadow, original: shadow.get(f"candidate_{target}")),
            ("matched_reduced_feature_v1",
             lambda shadow, original: shadow.get(f"matched_v1_{target}")),
            ("original_main_v1_archive",
             lambda shadow, original: original.get(
                 "expected_total_points" if target == "total_points"
                 else "expected_home_margin")),
        ):
            errors = [
                accessor(shadow, original)-actual_fn(home, away)
                for shadow, home, away, original in matched
                if accessor(shadow, original) is not None
            ]
            score_metrics[target][label] = {
                "games": len(errors),
                "mae": _round(_mean([abs(e) for e in errors])),
                "bias": _round(_mean(errors)),
            }
    return {
        **base,
        "status": "descriptive_only" if len(matched) < MIN_REVIEW
                  else "paired_review_checkpoint",
        "matched_games": len(matched),
        "main_v1_settled_records": len(cohort),
        "wave2_settled_records": len(scored),
        "not_matching_same_game": len(scored)-len(matched),
        "moneyline": metrics,
        "score_projections": score_metrics,
        "limitation": (
            "Only exact same games with original archived V1 pregame forecasts "
            "and verified final scores. Original V1 is NOT the same as matched "
            "reduced-feature V1. No frozen-model-weight proof, sports-book "
            "odds, profitability or model promotion."
        ),
    }


def evidence_progress(settled_count, forecast_count, pending_count):
    return {
        "verified_forward_settlements": settled_count,
        "archived_forecasts": forecast_count,
        "pending_forecasts": pending_count,
        "review_checkpoint": MIN_REVIEW,
        "additional_verified_settlements_for_checkpoint": max(
            0, MIN_REVIEW - settled_count),
        "checkpoint_met": settled_count >= MIN_REVIEW,
        "status": ("review_checkpoint_reached" if settled_count >= MIN_REVIEW
                   else "collecting_prospective_games"),
        "threshold_is_not_evidence_of_model_edge": True,
        "no_synthetic_or_retroactive_forecasts": True,
        "no_publishing_or_model_promotion": True,
    }
