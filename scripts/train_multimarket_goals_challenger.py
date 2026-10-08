"""Train a FULL-TIME GOALS shadow challenger on permissioned historical data.

Usage:
  python -m scripts.train_multimarket_goals_challenger \
    --input-csv /secure/permissioned_football_history.csv \
    --report /tmp/multimarket_report.json

The command never imports legacy training CSV, touches DB, updates model
registry, or publishes selections. Artifacts are optional and must not be
placed in production model paths. "rights_basis" fields are assertions that
operators must independently verify; they are not a legal license.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from leagues.goal_distribution_challenger import probabilities
from leagues.multimarket_training_dataset import (
    FEATURES, chronological_groups, read_permissioned_csv,
)

EVALUATE_MARKETS = (
    "over_0_5", "over_1_5", "over_2_5", "over_3_5",
    "under_3_5", "under_4_5", "btts_yes", "btts_no",
    "home_over_0_5", "away_over_0_5",
    "home_over_1_5", "away_over_1_5",
    "home_or_draw", "away_or_draw", "home_win", "draw", "away_win",
)


def _score(rows: list[dict], predicted: list[dict],
           train_rows: list[dict]) -> dict:
    """Evaluate binary forecasts against train-cohort base rates, not a
    random benchmark or a post-test frequency."""
    results = {}
    for market in EVALUATE_MARKETS:
        labels = [int(r["labels"][market]) for r in rows]
        probabilities_ = [max(1e-6, min(1 - 1e-6, p[market]))
                          for p in predicted]
        reference = sum(int(r["labels"][market]) for r in train_rows) / len(train_rows)
        reference = max(1e-6, min(1 - 1e-6, reference))
        def brier(p):
            return sum((forecast - y) ** 2 for forecast, y in zip(p, labels)) / len(labels)
        def logloss(p):
            return -sum(y * math.log(forecast) + (1-y) * math.log(1-forecast)
                        for forecast, y in zip(p, labels)) / len(labels)
        bins: dict[int, list[tuple[float, int]]] = {}
        for forecast, y in zip(probabilities_, labels):
            bins.setdefault(min(9, int(forecast * 10)), []).append((forecast, y))
        ece = sum(len(bucket) / len(labels) *
                  abs(sum(p for p, _ in bucket) / len(bucket)
                      - sum(y for _, y in bucket) / len(bucket))
                  for bucket in bins.values())
        results[market] = {
            "n": len(rows),
            "brier": round(brier(probabilities_), 6),
            "baseline_brier": round(brier([reference] * len(rows)), 6),
            "log_loss": round(logloss(probabilities_), 6),
            "baseline_log_loss": round(logloss([reference] * len(rows)), 6),
            "ece": round(ece, 6),
            "brier_better_than_train_base": brier(probabilities_) < brier([reference] * len(rows)),
        }
    return results


def train(rows: list[dict]) -> dict:
    """Return an evaluation report and two candidate models; no persistence."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    training, calibration, test = chronological_groups(rows)
    x_train = [r["feature_vector"] for r in training]
    x_calib = [r["feature_vector"] for r in calibration]
    x_test = [r["feature_vector"] for r in test]
    models = {}
    for side in ("home", "away"):
        predictor = HistGradientBoostingRegressor(
            loss="poisson", max_iter=120, max_leaf_nodes=15,
            min_samples_leaf=25, l2_regularization=3.0, random_state=42,
        )
        predictor.fit(x_train, [r[f"{side}_goals"] for r in training])
        models[side] = predictor

    def predict(x):
        h = models["home"].predict(x)
        a = models["away"].predict(x)
        return [probabilities(float(max(0.0, home)), float(max(0.0, away)))
                for home, away in zip(h, a)]

    # Calibration is intentionally reserved for evaluation of future methods.
    # No isotonic postprocessor is fit from tiny market-wise sample sizes;
    # holdout remains untouched while we measure unadjusted model skill.
    calib_probs = predict(x_calib)
    test_probs = predict(x_test)
    report = {
        "status": "OFFLINE_CHALLENGER_ONLY",
        "production_unchanged": True,
        "market_activation": False,
        "model_type": "independent_poisson_xg_hist_gradient_boosting_challenger",
        "model_inputs": list(FEATURES),
        "training_rows": len(training),
        "calibration_rows": len(calibration),
        "test_rows": len(test),
        "source_counts": dict(Counter(r["source_id"] for r in rows)),
        "rights_basis_counts": dict(Counter(r["rights_basis"] for r in rows)),
        "training_last_kickoff": max(r["kickoff_utc"] for r in training).isoformat(),
        "calibration_first_kickoff": min(r["kickoff_utc"] for r in calibration).isoformat(),
        "test_first_kickoff": min(r["kickoff_utc"] for r in test).isoformat(),
        "calibration": _score(calibration, calib_probs, training),
        "test": _score(test, test_probs, training),
        "recommendation": "SHADOW_EVALUATION_ONLY — no automatic promotion",
    }
    return {"report": report, "models": models}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.input_csv.resolve() == args.report.resolve():
        parser.error("Report and source must be different files")

    rows = read_permissioned_csv(args.input_csv)
    result = train(rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result["report"], indent=2, sort_keys=True),
                           encoding="utf-8")
    print(json.dumps({
        "status": result["report"]["status"],
        "report": str(args.report),
        "training_rows": result["report"]["training_rows"],
        "test_rows": result["report"]["test_rows"],
        "production_unchanged": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
