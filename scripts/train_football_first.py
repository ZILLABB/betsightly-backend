"""Train an isolated football-first expected-goals challenger.

This script never writes to ``models/api_football`` and refuses to overwrite an
existing artifact. It uses one rolling feature builder for historical and live
inference semantics and strict chronological train/calibration/test periods.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from leagues.football_feature_contract import (
    FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, FootballHistoryState,
    validate_contract,
)
from leagues.football_first_model import (
    ARTIFACT_FORMAT_VERSION, ScaledGoalRegressor, coherent_probabilities,
)


def build_dataset(frame: pd.DataFrame) -> tuple[np.ndarray, ...]:
    required = {"date", "league_id", "home_team", "away_team",
                "home_score", "away_score"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"MISSING_COLUMNS:{','.join(sorted(missing))}")
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=list(required)).sort_values(
        ["date", "league_id", "home_team", "away_team"], kind="stable"
    )
    state = FootballHistoryState()
    rows, home_y, away_y, dates, odds_rows, leagues = [], [], [], [], [], []
    for match_date, day in data.groupby("date", sort=True):
        pending = day.to_dict("records")
        for match in pending:
            vector = state.features(
                league_id=match["league_id"], home_team=match["home_team"],
                away_team=match["away_team"], as_of=match_date,
            )
            # Version 1 trains only once both teams have at least five earlier
            # results. Missing history remains supported at inference and is
            # explicitly surfaced, but does not dominate training.
            values = vector.as_dict()
            if values["home_history_coverage"] < .5 or values["away_history_coverage"] < .5:
                continue
            rows.append(vector.as_list())
            home_y.append(int(match["home_score"]))
            away_y.append(int(match["away_score"]))
            dates.append(match_date.to_datetime64())
            odds_rows.append([
                match.get("avg_odds_home"), match.get("avg_odds_draw"),
                match.get("avg_odds_away"), match.get("avg_odds_over25"),
                match.get("avg_odds_under25"),
            ])
            leagues.append(str(match["league_id"]))
        for match in pending:
            state.observe(
                league_id=match["league_id"], home_team=match["home_team"],
                away_team=match["away_team"], played_at=match_date,
                home_goals=int(match["home_score"]),
                away_goals=int(match["away_score"]),
            )
    return (np.asarray(rows, dtype=float), np.asarray(home_y, dtype=int),
            np.asarray(away_y, dtype=int), np.asarray(dates),
            np.asarray(odds_rows, dtype=float), np.asarray(leagues))


def _split(dates: np.ndarray) -> tuple[slice, slice, slice]:
    n = len(dates)
    if n < 1000:
        raise ValueError("INSUFFICIENT_TRAINING_ROWS")
    train_end = int(n * .70)
    calibration_end = int(n * .85)
    # Never divide fixtures from one calendar date between partitions. All
    # same-day features were built from the same earlier state, and sharing a
    # day across train/calibration or calibration/test weakens the temporal
    # isolation promised by the report.
    while train_end < n and dates[train_end] == dates[train_end - 1]:
        train_end += 1
    while calibration_end < n and dates[calibration_end] == dates[calibration_end - 1]:
        calibration_end += 1
    if not (0 < train_end < calibration_end < n):
        raise ValueError("INVALID_CHRONOLOGICAL_PARTITIONS")
    return slice(0, train_end), slice(train_end, calibration_end), slice(calibration_end, n)


def _bootstrap_mean_ci(values: np.ndarray, seed: int = 42) -> list[float] | None:
    if len(values) < 100:
        return None
    rng = np.random.default_rng(seed)
    means = [float(rng.choice(values, size=len(values), replace=True).mean())
             for _ in range(500)]
    return [round(float(np.quantile(means, .025)), 6),
            round(float(np.quantile(means, .975)), 6)]


def _tune_hybrid_weights(home_y, away_y, home_lam, away_lam, odds) -> dict:
    truth_result = np.where(home_y > away_y, 0, np.where(home_y == away_y, 1, 2))
    truth_over = (home_y + away_y > 2).astype(float)
    probabilities = [coherent_probabilities(h, a) for h, a in zip(home_lam, away_lam)]
    football_result = np.asarray([[p["home_win"], p["draw"], p["away_win"]]
                                  for p in probabilities])
    football_over = np.asarray([p["over_2_5"] for p in probabilities])
    eps = 1e-12
    weights = {"result_football_weight": 0.0, "over_2_5_football_weight": 0.0}
    valid = np.isfinite(odds[:, :3]).all(axis=1) & (odds[:, :3] > 1).all(axis=1)
    if valid.any():
        market = 1 / odds[valid, :3]
        market /= market.sum(axis=1, keepdims=True)
        truth = truth_result[valid]
        candidates = []
        for weight in np.linspace(0, 1, 21):
            blended = weight * football_result[valid] + (1-weight) * market
            loss = -np.log(np.clip(blended[np.arange(len(truth)), truth], eps, 1)).mean()
            candidates.append((loss, float(weight)))
        weights["result_football_weight"] = min(candidates)[1]
    valid = np.isfinite(odds[:, 3:5]).all(axis=1) & (odds[:, 3:5] > 1).all(axis=1)
    if valid.any():
        market = 1 / odds[valid, 3:5]
        market_over = market[:, 0] / market.sum(axis=1)
        truth = truth_over[valid]
        candidates = []
        for weight in np.linspace(0, 1, 21):
            blended = weight * football_over[valid] + (1-weight) * market_over
            loss = -(truth*np.log(np.clip(blended, eps, 1)) +
                     (1-truth)*np.log(np.clip(1-blended, eps, 1))).mean()
            candidates.append((loss, float(weight)))
        weights["over_2_5_football_weight"] = min(candidates)[1]
    return weights


def _scores(home_y, away_y, home_lam, away_lam, odds, dates, leagues,
            hybrid_weights) -> dict:
    result_true = np.where(home_y > away_y, 0, np.where(home_y == away_y, 1, 2))
    total_true = (home_y + away_y > 2).astype(float)
    probs = [coherent_probabilities(h, a) for h, a in zip(home_lam, away_lam)]
    result_probs = np.asarray([[p["home_win"], p["draw"], p["away_win"]] for p in probs])
    over25 = np.asarray([p["over_2_5"] for p in probs])
    eps = 1e-12
    result_loss_rows = -np.log(np.clip(result_probs[np.arange(len(result_true)), result_true], eps, 1))
    result_log_loss = result_loss_rows.mean()
    result_brier = np.square(result_probs - np.eye(3)[result_true]).sum(axis=1).mean()
    over_log_loss = -(total_true * np.log(np.clip(over25, eps, 1)) +
                      (1 - total_true) * np.log(np.clip(1 - over25, eps, 1))).mean()
    over_brier = np.square(over25 - total_true).mean()

    benchmark = {"n_1x2": 0, "result_log_loss": None, "result_brier": None,
                 "n_ou25": 0, "over_2_5_log_loss": None, "over_2_5_brier": None}
    hybrid = {"weights_selected_on_calibration": hybrid_weights,
              "n_1x2": 0, "result_log_loss": None, "result_brier": None,
              "n_ou25": 0, "over_2_5_log_loss": None, "over_2_5_brier": None}
    incremental = {"result_log_loss_difference": None,
                   "result_log_loss_difference_95ci": None,
                   "over_2_5_log_loss_difference": None,
                   "over_2_5_log_loss_difference_95ci": None}
    one_x_two = odds[:, :3]
    valid = np.isfinite(one_x_two).all(axis=1) & (one_x_two > 1).all(axis=1)
    if valid.any():
        implied = 1 / one_x_two[valid]
        implied /= implied.sum(axis=1, keepdims=True)
        truth = result_true[valid]
        bookmaker_losses = -np.log(np.clip(implied[np.arange(len(truth)), truth], eps, 1))
        difference = result_loss_rows[valid] - bookmaker_losses
        benchmark.update({
            "n_1x2": int(valid.sum()),
            "result_log_loss": round(float(-np.log(np.clip(implied[np.arange(len(truth)), truth], eps, 1)).mean()), 6),
            "result_brier": round(float(np.square(implied - np.eye(3)[truth]).sum(axis=1).mean()), 6),
        })
        weight = hybrid_weights["result_football_weight"]
        blended = weight * result_probs[valid] + (1-weight) * implied
        hybrid.update({
            "n_1x2": int(valid.sum()),
            "result_log_loss": round(float(-np.log(np.clip(
                blended[np.arange(len(truth)), truth], eps, 1)).mean()), 6),
            "result_brier": round(float(np.square(
                blended - np.eye(3)[truth]).sum(axis=1).mean()), 6),
        })
        incremental.update({
            "result_log_loss_difference": round(float(difference.mean()), 6),
            "result_log_loss_difference_95ci": _bootstrap_mean_ci(difference),
        })
    ou = odds[:, 3:5]
    valid_ou = np.isfinite(ou).all(axis=1) & (ou > 1).all(axis=1)
    if valid_ou.any():
        implied = 1 / ou[valid_ou]
        p_over = implied[:, 0] / implied.sum(axis=1)
        truth = total_true[valid_ou]
        model_losses = -(truth * np.log(np.clip(over25[valid_ou], eps, 1)) +
                         (1-truth)*np.log(np.clip(1-over25[valid_ou], eps, 1)))
        bookmaker_losses = -(truth * np.log(np.clip(p_over, eps, 1)) +
                              (1-truth)*np.log(np.clip(1-p_over, eps, 1)))
        difference = model_losses - bookmaker_losses
        benchmark.update({
            "n_ou25": int(valid_ou.sum()),
            "over_2_5_log_loss": round(float(-(truth * np.log(np.clip(p_over, eps, 1)) + (1-truth)*np.log(np.clip(1-p_over, eps, 1))).mean()), 6),
            "over_2_5_brier": round(float(np.square(p_over-truth).mean()), 6),
        })
        weight = hybrid_weights["over_2_5_football_weight"]
        blended = weight * over25[valid_ou] + (1-weight) * p_over
        hybrid.update({
            "n_ou25": int(valid_ou.sum()),
            "over_2_5_log_loss": round(float(-(truth*np.log(np.clip(blended, eps, 1)) +
                (1-truth)*np.log(np.clip(1-blended, eps, 1))).mean()), 6),
            "over_2_5_brier": round(float(np.square(blended-truth).mean()), 6),
        })
        incremental.update({
            "over_2_5_log_loss_difference": round(float(difference.mean()), 6),
            "over_2_5_log_loss_difference_95ci": _bootstrap_mean_ci(difference, seed=43),
        })
    slices = {}
    seasons = np.asarray([str(pd.Timestamp(value).year) for value in dates])
    for label, groups in (("by_season", seasons), ("by_league", leagues)):
        result = {}
        for group in sorted(set(groups)):
            mask = groups == group
            if mask.sum() < 50:
                continue
            result[str(group)] = {
                "n": int(mask.sum()),
                "result_log_loss": round(float(result_loss_rows[mask].mean()), 6),
                "result_brier": round(float(np.square(
                    result_probs[mask] - np.eye(3)[result_true[mask]]
                ).sum(axis=1).mean()), 6),
            }
        slices[label] = result
    return {
        "football_first": {
            "n": len(result_true),
            "result_log_loss": round(float(result_log_loss), 6),
            "result_brier": round(float(result_brier), 6),
            "over_2_5_log_loss": round(float(over_log_loss), 6),
            "over_2_5_brier": round(float(over_brier), 6),
            "mean_home_goals": round(float(np.mean(home_lam)), 6),
            "mean_away_goals": round(float(np.mean(away_lam)), 6),
        },
        "bookmaker_no_vig": benchmark,
        "calibration_selected_hybrid": hybrid,
        "incremental_vs_bookmaker": incremental,
        **slices,
    }


def train(input_csv: Path, output: Path) -> dict:
    compatible, reason = validate_contract()
    if not compatible:
        raise ValueError(reason)
    if output.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{output}")
    started = time.perf_counter()
    frame = pd.read_csv(input_csv, low_memory=False)
    X, home_y, away_y, dates, odds, leagues = build_dataset(frame)
    train_slice, calibration_slice, test_slice = _split(dates)
    kwargs = dict(loss="poisson", learning_rate=.05, max_iter=180,
                  max_leaf_nodes=24, min_samples_leaf=35,
                  l2_regularization=1.0, random_state=42)
    home_base = HistGradientBoostingRegressor(**kwargs).fit(X[train_slice], home_y[train_slice])
    away_base = HistGradientBoostingRegressor(**kwargs).fit(X[train_slice], away_y[train_slice])
    home_cal_pred = np.clip(home_base.predict(X[calibration_slice]), .05, 6)
    away_cal_pred = np.clip(away_base.predict(X[calibration_slice]), .05, 6)
    home_scale = float(home_y[calibration_slice].sum() / max(home_cal_pred.sum(), 1e-9))
    away_scale = float(away_y[calibration_slice].sum() / max(away_cal_pred.sum(), 1e-9))
    home_model = ScaledGoalRegressor(home_base, home_scale)
    away_model = ScaledGoalRegressor(away_base, away_scale)
    home_test = np.clip(home_model.predict(X[test_slice]), .05, 6)
    away_test = np.clip(away_model.predict(X[test_slice]), .05, 6)
    hybrid_weights = _tune_hybrid_weights(
        home_y[calibration_slice], away_y[calibration_slice],
        np.clip(home_model.predict(X[calibration_slice]), .05, 6),
        np.clip(away_model.predict(X[calibration_slice]), .05, 6),
        odds[calibration_slice],
    )
    comparison = _scores(home_y[test_slice], away_y[test_slice], home_test,
                         away_test, odds[test_slice], dates[test_slice],
                         leagues[test_slice], hybrid_weights)
    model_version = f"football-first-v1-{pd.Timestamp(dates[train_slice][-1]).strftime('%Y%m%d')}"
    metadata = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "model_version": model_version,
        "promotion_status": "CHALLENGER",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "uses_bookmaker_features": False,
        "dataset": str(input_csv.as_posix()),
        "dataset_sha256": hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        "sample_count": len(X),
        "partitions": {
            "train": {"n": train_slice.stop, "start": str(pd.Timestamp(dates[0]).date()),
                      "end": str(pd.Timestamp(dates[train_slice][-1]).date())},
            "calibration": {"n": calibration_slice.stop-calibration_slice.start,
                            "start": str(pd.Timestamp(dates[calibration_slice][0]).date()),
                            "end": str(pd.Timestamp(dates[calibration_slice][-1]).date())},
            "test": {"n": len(X)-test_slice.start,
                     "start": str(pd.Timestamp(dates[test_slice][0]).date()),
                     "end": str(pd.Timestamp(dates[-1]).date())},
        },
        "calibration": {"method": "goal-rate scaling on calibration era",
                        "home_scale": home_scale, "away_scale": away_scale},
        "comparison": comparison,
        "uncertainty": {"status": "PROVISIONAL", "method": "not yet interval-calibrated"},
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_seconds": round(time.perf_counter()-started, 3),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"metadata": metadata, "home_goals_model": home_model,
                 "away_goals_model": away_model}, output)
    artifact_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    report = {**metadata, "artifact_sha256": artifact_hash}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=ROOT / "data/api-football/matches.csv")
    parser.add_argument("--output", type=Path, required=True,
                        help="New isolated challenger .joblib path")
    args = parser.parse_args()
    report = train(args.input, args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
