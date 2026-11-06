"""Read-only attribution boundaries and common-error diagnostics for NBA Wave 2.

Input is ONLY the *already validated* (forecast, verified home, verified away)
cohort from research_wave2_report. A modern boxscore or feature recomputation
must not masquerade as the immutable historical pre-tipoff feature vector.
No retraining, threshold changes, paper-archive writes or publication.
"""
from __future__ import annotations

import math

from basketball.research_advanced_features import (
    FEATURE_COLUMNS as ADVANCED_FEATURES, ADVANCED_COLS, VERSION,
)
from basketball.research_features import FEATURE_COLUMNS as V1_FEATURES

EXAMPLE_IDS = ("401909285", "401909910", "401909911")
LARGE_ERROR_POINTS = 20.0


def _r(value):
    return round(value, 5) if value is not None else None


def _average(values):
    return sum(values)/len(values) if values else None


def _corr(x, y):
    """Descriptive correlation of paired signed errors, no independence claim."""
    if len(x) < 3 or len(x) != len(y):
        return None
    xm, ym = _average(x), _average(y)
    a = [v-xm for v in x]
    b = [v-ym for v in y]
    xx = sum(v*v for v in a)
    yy = sum(v*v for v in b)
    if xx < 1e-15 or yy < 1e-15:
        return None
    return _r(sum(u*v for u, v in zip(a,b)) / math.sqrt(xx*yy))


def _scores(row, home, away):
    out = {}
    for target, actual in (
        ("total_points", home+away), ("home_margin", home-away),
    ):
        cand = row.get(f"candidate_{target}")
        base = row.get(f"matched_v1_{target}")
        if cand is None or base is None:
            out[target] = {"actual": actual, "candidate": cand,
                           "matched_v1": base, "both_present": False}
            continue
        ce, be = cand-actual, base-actual
        out[target] = {
            "actual": actual,
            "candidate": cand,
            "matched_v1": base,
            "both_present": True,
            "candidate_error": _r(ce),
            "matched_v1_error": _r(be),
            "candidate_abs_error": _r(abs(ce)),
            "matched_v1_abs_error": _r(abs(be)),
            "candidate_better_abs_error": abs(ce) < abs(be),
            "matched_v1_better_abs_error": abs(be) < abs(ce),
            "both_same_error_direction": ce*be > 0,
            "both_large_errors": (
                abs(ce) >= LARGE_ERROR_POINTS
                and abs(be) >= LARGE_ERROR_POINTS
            ),
        }
    return out


def shared_input_error_audit(scored, final_lookup: dict):
    """Quantify *shared* failures, not speculative causal feature attribution.

    All scores, names, fixture IDs and team IDs come from finals that the
    calling report independently checked against signed pregame records.
    Pre-tipoff feature values were NOT stored in the legacy shadow JSONL.
    """
    pairs = {}
    for row, home, away in scored:
        gid = str(row["game_id"])
        verified = final_lookup[gid]
        pairs[gid] = {
            "game_id": gid, "fixture_date": row["fixture_date"],
            "away_team": verified.get("away_name"),
            "home_team": verified.get("home_name"),
            "away_id": str(row["away_id"]),
            "home_id": str(row["home_id"]),
            "verified_away_score": away,
            "verified_home_score": home,
            "candidate_home_win_probability": (
                row["candidate_home_win_probability"]),
            "matched_v1_home_win_probability": (
                row["matched_v1_home_win_probability"]),
            "score_errors": _scores(row, home, away),
            "source_feature_schema": row.get("source_feature_schema"),
            "pregame_feature_values_in_original_archive": (
                isinstance(row.get("pregame_feature_snapshot"), dict)
            ),
        }

    target_metrics = {}
    large_examples = []
    for target in ("total_points", "home_margin"):
        paired = [
            (item, item["score_errors"][target])
            for item in pairs.values()
            if item["score_errors"][target]["both_present"]
        ]
        ce = [r["candidate_error"] for _, r in paired]
        be = [r["matched_v1_error"] for _, r in paired]
        same_direction = sum(r["both_same_error_direction"] for _, r in paired)
        large = sum(r["both_large_errors"] for _, r in paired)
        winner_sign_reversal = 0
        if target == "home_margin":
            winner_sign_reversal = sum(
                int(r["actual"] * r["candidate"] < 0
                    and r["actual"] * r["matched_v1"] < 0)
                for _, r in paired
            )
        target_metrics[target] = {
            "paired_games": len(paired),
            "candidate_mae": _r(_average([abs(x) for x in ce])),
            "matched_v1_mae": _r(_average([abs(x) for x in be])),
            "candidate_minus_v1_mae": (
                _r(_average([abs(x)-abs(y) for x,y in zip(ce,be)]))),
            "both_models_error_same_direction_games": same_direction,
            "both_models_error_same_direction_share": (
                _r(same_direction/len(paired)) if paired else None),
            "signed_error_correlation": _corr(ce,be),
            "candidate_lower_absolute_error_games": sum(
                r["candidate_better_abs_error"] for _, r in paired),
            "matched_v1_lower_absolute_error_games": sum(
                r["matched_v1_better_abs_error"] for _, r in paired),
            "both_models_absolute_error_at_least_20_games": large,
            "both_models_wrong_home_margin_sign_games": (
                winner_sign_reversal if target == "home_margin" else None),
            "diagnostic_error_threshold_points": LARGE_ERROR_POINTS,
        }
        for item, values in paired:
            if values["both_large_errors"]:
                large_examples.append({
                    "game_id": item["game_id"],
                    "fixture_date": item["fixture_date"],
                    "away_team": item["away_team"],
                    "home_team": item["home_team"],
                    "target": target,
                    "actual": values["actual"],
                    "candidate": values["candidate"],
                    "matched_v1": values["matched_v1"],
                    "candidate_error": values["candidate_error"],
                    "matched_v1_error": values["matched_v1_error"],
                    "shared_abs_error_floor": min(
                        values["candidate_abs_error"],
                        values["matched_v1_abs_error"]),
                })
    large_examples.sort(
        key=lambda v: (-v["shared_abs_error_floor"], v["game_id"], v["target"]))

    exact_ids = [
        {"game_id": gid, "status": "verified_settled", **pairs[gid]}
        if gid in pairs else
        {"game_id": gid, "status": "not_in_verified_settled_cohort"}
        for gid in EXAMPLE_IDS
    ]

    feature_version_counts = {}
    for item in pairs.values():
        key = item["source_feature_schema"] or "unrecorded"
        feature_version_counts[key] = feature_version_counts.get(key,0)+1

    return {
        "status": "descriptive_only" if scored else "awaiting_verified_finals",
        "verified_settled_games": len(scored),
        "target_metrics": target_metrics,
        "large_shared_score_misses": large_examples[:12],
        "priority_fixture_audit": exact_ids,
        "feature_contract": {
            "v1_feature_count": len(V1_FEATURES),
            "v1_feature_names": list(V1_FEATURES),
            "advanced_additional_feature_count": len(ADVANCED_COLS),
            "advanced_additional_feature_names": list(ADVANCED_COLS),
            "advanced_total_feature_count": len(ADVANCED_FEATURES),
            "matched_v1_uses_first_14_features": (
                len(V1_FEATURES) == 14
                and ADVANCED_FEATURES[:14] == V1_FEATURES),
            "source_feature_schema_expected": VERSION,
            "source_feature_schemas_in_verified_records": feature_version_counts,
            "original_pregame_feature_vector_archived_games": sum(
                item["pregame_feature_values_in_original_archive"]
                for item in pairs.values()),
            "frozen_as_of_feature_reconstruction": "not_supported_for_legacy_records",
            "new_snapshot_feature_vectors_available": sum(
                item["pregame_feature_values_in_original_archive"]
                for item in pairs.values()),
            "legacy_settled_games_without_feature_vectors": sum(
                not item["pregame_feature_values_in_original_archive"]
                for item in pairs.values()),
            "injury_inputs_in_frozen_model": False,
        },
        "identities_checked_upstream": True,
        "no_causal_feature_attribution": True,
        "large_error_threshold_is_not_a_prediction_filter": True,
        "no_retraining_or_forecast_rewrite": True,
        "research_only": True,
        "no_writes": True,
        "interpretation": (
            "Same-direction errors imply similar residuals, not a proven "
            "defect in pace, efficiency, rest, injuries or data identity. "
            "Legacy shadow records do not contain frozen pre-tipoff feature "
            "values. Only new signed forecasts may include exact frozen "
            "model inputs. Current fixture/boxscore files cannot reproduce "
            "historical availability or exact inputs for legacy forecasts."
        ),
    }
