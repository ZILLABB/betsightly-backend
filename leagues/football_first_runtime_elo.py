"""Phase-8 runtime-compatible Elo feature experiment.

No deployed football-first model is changed here. Domestic leagues only are
evaluated initially because the historical corpus lacks trustworthy
neutral-venue context for tournament fixtures.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
import numpy as np
import pandas as pd

from leagues.canonical_identity import normalize_team
from leagues.competition_registry import competition_for
from leagues.elo_core import (
    ELO_CORE_VERSION,
    HISTORY_DAYS,
    feature_snapshot,
    run_elo,
)
from leagues.football_first_challenger import TARGET_COLUMNS
from leagues.football_first_runtime_core import (
    RUNTIME_FEATURE_COLUMNS,
    normalize_runtime_core_frame,
)
from leagues.football_first_stability import _evaluate_target_fold, temporal_folds

RUNTIME_ELO_FEATURE_VERSION = "football-first-runtime-elo-v1"

RUNTIME_ELO_FEATURE_COLUMNS = [
    "runtime_elo_available",
    "runtime_elo_home_expectation",
    "runtime_elo_diff_scaled",
    "runtime_elo_evidence_scaled",
]

API_LEAGUE_TO_ESPN_SLUG = {
    39: "eng.1", 40: "eng.2", 61: "fra.1", 62: "fra.2",
    71: "bra.1", 78: "ger.1", 79: "ger.2", 88: "ned.1",
    94: "por.1", 98: "jpn.1", 103: "nor.1", 106: "pol.1",
    113: "swe.1", 119: "den.1", 128: "arg.1", 135: "ita.1",
    136: "ita.2", 140: "esp.1", 141: "esp.2", 144: "bel.1",
    169: "chn.1", 179: "sco.1", 197: "gre.1", 203: "tur.1",
    218: "aut.1", 244: "fin.1", 253: "usa.1", 262: "mex.1",
    265: "chi.1", 283: "rou.1", 292: "kor.1", 307: "sau.1",
}


def _eligible_domestic_slug(league_id: int) -> str | None:
    slug = API_LEAGUE_TO_ESPN_SLUG.get(int(league_id))
    if not slug:
        return None
    meta = competition_for(slug)
    if (
        meta is None
        or meta.team_type != "CLUB"
        or meta.competition_type != "LEAGUE"
        or meta.format != "LEAGUE"
        or meta.possible_neutral_venue
    ):
        return None
    return slug


def _team(name: str) -> str:
    return normalize_team(str(name or ""))


def runtime_elo_feature_vector(fixture: dict, all_ratings: dict) -> dict:
    slug = str(fixture.get("league_slug") or "")
    meta = competition_for(slug)
    if (
        meta is None
        or meta.team_type != "CLUB"
        or meta.competition_type != "LEAGUE"
        or meta.format != "LEAGUE"
        or meta.possible_neutral_venue
    ):
        features = {
            "runtime_elo_available": 0.0,
            "runtime_elo_home_expectation": 0.5,
            "runtime_elo_diff_scaled": 0.0,
            "runtime_elo_evidence_scaled": 0.0,
        }
        return {
            "status": "UNSUPPORTED_CONTEXT",
            "feature_version": RUNTIME_ELO_FEATURE_VERSION,
            "elo_core_version": ELO_CORE_VERSION,
            "features": features,
            "vector": [features[c] for c in RUNTIME_ELO_FEATURE_COLUMNS],
        }

    home_name = (fixture.get("home") or {}).get("name") or ""
    away_name = (fixture.get("away") or {}).get("name") or ""
    pool = all_ratings.get(slug) or {}
    home = pool.get(home_name)
    away = pool.get(away_name)

    snapshot = feature_snapshot(
        home.get("rating") if home else None,
        away.get("rating") if away else None,
        int(home.get("matches") or 0) if home else 0,
        int(away.get("matches") or 0) if away else 0,
        neutral=bool(fixture.get("neutral_venue")),
    )
    features = {
        "runtime_elo_available": float(snapshot["elo_available"]),
        "runtime_elo_home_expectation": float(snapshot["elo_home_expectation"]),
        "runtime_elo_diff_scaled": float(snapshot["elo_diff_scaled"]),
        "runtime_elo_evidence_scaled": float(snapshot["elo_evidence_scaled"]),
    }
    return {
        "status": snapshot["status"],
        "feature_version": RUNTIME_ELO_FEATURE_VERSION,
        "elo_core_version": ELO_CORE_VERSION,
        "rating_evidence": snapshot["rating_evidence"],
        "features": features,
        "vector": [features[c] for c in RUNTIME_ELO_FEATURE_COLUMNS],
    }


def attach_historical_runtime_elo(
    combined_results: pd.DataFrame,
    runtime_features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    frame = runtime_features.copy()
    for column in RUNTIME_ELO_FEATURE_COLUMNS:
        frame[column] = 0.0
    frame["runtime_elo_home_expectation"] = 0.5

    if frame.empty:
        return frame, {
            "feature_version": RUNTIME_ELO_FEATURE_VERSION,
            "elo_core_version": ELO_CORE_VERSION,
            "samples": 0,
            "available": 0,
            "unsupported_context": 0,
            "insufficient_evidence": 0,
        }

    source = combined_results.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.dropna(
        subset=[
            "date", "league_id", "home_team", "away_team",
            "home_score", "away_score",
        ]
    )
    source["league_id"] = source["league_id"].astype(int)

    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["league_id"] = frame["league_id"].astype(int)

    available = 0
    unsupported = 0
    insufficient = 0
    window_rebuilds = 0

    for league_id, targets in frame.groupby("league_id", sort=True):
        slug = _eligible_domestic_slug(int(league_id))
        if slug is None:
            unsupported += len(targets)
            continue

        history = source[source["league_id"] == int(league_id)].sort_values(
            ["date", "home_team", "away_team"]
        )
        if history.empty:
            insufficient += len(targets)
            continue

        history_rows = []
        history_dates = []
        for row in history.to_dict("records"):
            day = pd.Timestamp(row["date"]).normalize()
            history_dates.append(day)
            history_rows.append({
                "date": day,
                "home": _team(row["home_team"]),
                "away": _team(row["away_team"]),
                "hs": int(row["home_score"]),
                "as": int(row["away_score"]),
                "neutral": False,
            })

        target_days = frame.loc[targets.index, "date"].dt.normalize()
        for target_day, day_targets in targets.groupby(target_days, sort=True):
            target_day = pd.Timestamp(target_day).normalize()
            start_day = target_day - pd.Timedelta(days=HISTORY_DAYS)
            left = bisect_left(history_dates, start_day)
            right = bisect_left(history_dates, target_day)
            ratings, counts = run_elo(history_rows[left:right])
            window_rebuilds += 1

            for index in day_targets.index:
                home = _team(frame.at[index, "home_team"])
                away = _team(frame.at[index, "away_team"])
                snapshot = feature_snapshot(
                    ratings.get(home),
                    ratings.get(away),
                    counts.get(home, 0),
                    counts.get(away, 0),
                    neutral=False,
                )
                if snapshot["status"] == "READY":
                    available += 1
                else:
                    insufficient += 1

                frame.at[index, "runtime_elo_available"] = float(
                    snapshot["elo_available"]
                )
                frame.at[index, "runtime_elo_home_expectation"] = float(
                    snapshot["elo_home_expectation"]
                )
                frame.at[index, "runtime_elo_diff_scaled"] = float(
                    snapshot["elo_diff_scaled"]
                )
                frame.at[index, "runtime_elo_evidence_scaled"] = float(
                    snapshot["elo_evidence_scaled"]
                )

    return frame, {
        "feature_version": RUNTIME_ELO_FEATURE_VERSION,
        "elo_core_version": ELO_CORE_VERSION,
        "history_window_days": HISTORY_DAYS,
        "same_day_results_visible": False,
        "samples": len(frame),
        "available": available,
        "availability_rate": round(available / len(frame), 6),
        "unsupported_context": unsupported,
        "insufficient_evidence": insufficient,
        "window_rebuilds": window_rebuilds,
        "provider_identity_parity": False,
        "provider_identity_blocker": (
            "offline corpus uses API-Football/OpenFootball names while "
            "live Elo is built from ESPN names"
        ),
    }


def _summary(rows: list[dict]) -> dict:
    skills = [float(row["log_loss_skill_vs_prior"]) for row in rows]
    if not skills:
        return {
            "fold_count": 0,
            "positive_skill_folds": 0,
            "median_skill": None,
            "minimum_skill": None,
            "family_selection_counts": {},
        }
    return {
        "fold_count": len(rows),
        "positive_skill_folds": sum(value > 0 for value in skills),
        "median_skill": round(float(np.median(skills)), 6),
        "minimum_skill": round(float(min(skills)), 6),
        "family_selection_counts": dict(
            Counter(row["selected_family"] for row in rows)
        ),
    }


def evaluate_runtime_elo_comparison(
    features: pd.DataFrame,
    *,
    n_folds: int = 4,
) -> dict:
    frame = normalize_runtime_core_frame(features)
    missing = [
        c for c in RUNTIME_ELO_FEATURE_COLUMNS
        if c not in frame.columns
    ]
    if missing:
        raise ValueError("Missing runtime Elo features: " + ", ".join(missing))

    folds = temporal_folds(frame, n_folds=n_folds)
    base_columns = list(RUNTIME_FEATURE_COLUMNS)
    expanded_columns = [*base_columns, *RUNTIME_ELO_FEATURE_COLUMNS]
    X_base = frame[base_columns].astype(float).to_numpy()
    X_elo = frame[expanded_columns].astype(float).to_numpy()
    targets = {}

    for target, target_column in TARGET_COLUMNS.items():
        y = frame[target_column].to_numpy()
        base_rows = []
        elo_rows = []
        for fold in folds:
            base = _evaluate_target_fold(X_base, y, fold)
            expanded = _evaluate_target_fold(X_elo, y, fold)
            if base is None or expanded is None:
                continue
            common = {
                "fold": int(fold["fold"]),
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
                "test_n": len(fold["test_indices"]),
            }
            base_rows.append({
                **common,
                "selected_family": base["selected_family"],
                "log_loss_skill_vs_prior": base["log_loss_skill_vs_prior"],
                "test": base["test"],
            })
            elo_rows.append({
                **common,
                "selected_family": expanded["selected_family"],
                "log_loss_skill_vs_prior": expanded["log_loss_skill_vs_prior"],
                "test": expanded["test"],
            })

        base_summary = _summary(base_rows)
        elo_summary = _summary(elo_rows)
        base_median = base_summary["median_skill"]
        elo_median = elo_summary["median_skill"]
        targets[target] = {
            "runtime_core_v1": {**base_summary, "folds": base_rows},
            "runtime_core_plus_elo": {**elo_summary, "folds": elo_rows},
            "median_skill_delta": (
                round(float(elo_median - base_median), 6)
                if elo_median is not None and base_median is not None
                else None
            ),
        }

    mr = targets.get("match_result") or {}
    delta = mr.get("median_skill_delta")
    elo_mr = mr.get("runtime_core_plus_elo") or {}

    return {
        "schema": 1,
        "experiment": "football_first_runtime_elo_comparison_v1",
        "base_feature_version": "football-first-runtime-core-v1",
        "elo_feature_version": RUNTIME_ELO_FEATURE_VERSION,
        "elo_core_version": ELO_CORE_VERSION,
        "base_feature_count": len(base_columns),
        "expanded_feature_count": len(expanded_columns),
        "expanded_feature_columns": expanded_columns,
        "targets": targets,
        "match_result_signal_improved": bool(
            delta is not None
            and delta > 0
            and elo_mr.get("positive_skill_folds", 0) >= 3
        ),
        "runtime_artifact_ready": False,
        "runtime_artifact_blockers": [
            "provider_identity_parity_not_closed",
            "historical_tournament_neutral_context_not_available",
            "prospective_v1_shadow_evidence_is_still_collecting",
        ],
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
    }
