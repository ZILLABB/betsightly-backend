"""Offline NBA moneyline research model with chronological holdouts.

Never import this from the public API. This module cannot publish or book.
Only actual historical results are accepted by the training path.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from basketball.research_features import FEATURE_COLUMNS, SCHEMA_VERSION, make_rows

MIN_REAL_GAMES = 300
MODEL_VERSION = "nba-moneyline-offline-v1"


def _dependencies():
    # Lazy imports: the public FastAPI app never needs to load ML dependencies.
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return joblib, np, LogisticRegression, accuracy_score, brier_score_loss, log_loss, make_pipeline, StandardScaler


def _metrics(labels, probabilities) -> dict:
    _, np, _, accuracy_score, brier_score_loss, log_loss, _, _ = _dependencies()
    y, probs = np.asarray(labels, dtype=int), np.asarray(probabilities, dtype=float)
    if len(y) == 0 or not np.isfinite(probs).all():
        raise ValueError("Evaluation requires finite predictions and real outcomes")
    return {
        "games": int(len(y)),
        "accuracy": round(float(accuracy_score(y, probs >= 0.5)), 5),
        "brier": round(float(brier_score_loss(y, probs)), 5),
        "log_loss": round(float(log_loss(y, probs, labels=[0, 1])), 5),
        "home_win_rate": round(float(y.mean()), 5),
    }


def chronological_split(rows: list[dict], min_games: int = MIN_REAL_GAMES):
    """Split distinct calendar days 70/15/15, oldest first, without shuffling."""
    finals = sorted((r for r in rows if r["status"] == "final"),
                    key=lambda r: (r["date"], r["game_id"]))
    if len(finals) < min_games:
        raise ValueError(f"Insufficient real NBA games: {len(finals)} < {min_games}")
    unique_dates = sorted({r["date"] for r in finals})
    if len(unique_dates) < 30:
        raise ValueError("Need at least 30 distinct game dates")
    b1, b2 = int(len(unique_dates) * 0.70), int(len(unique_dates) * 0.85)
    train_dates, validation_dates = set(unique_dates[:b1]), set(unique_dates[b1:b2])
    test_dates = set(unique_dates[b2:])
    subsets = [
        [r for r in finals if r["date"] in bucket]
        for bucket in (train_dates, validation_dates, test_dates)
    ]
    if min(len(rows) for rows in subsets) < 20:
        raise ValueError("Chronological holdouts too small")
    if set(subsets[0][i]["home_win"] for i in range(len(subsets[0]))) != {0, 1}:
        raise ValueError("Training set lacks both home-win classes")
    return tuple(subsets)


def _array(rows, np):
    x = np.asarray([r["features"] for r in rows], dtype=float)
    y = np.asarray([r["home_win"] for r in rows], dtype=int)
    if x.shape[1] != len(FEATURE_COLUMNS) or not np.isfinite(x).all():
        raise ValueError("Invalid or nonfinite NBA features")
    return x, y


def train_offline(games: list[dict], artifact_path: str | Path,
                  min_games: int = MIN_REAL_GAMES) -> dict:
    """Evaluate untouched later games and save a research-only artifact.

    Candidate regularization strengths are selected on validation only;
    the test set is inspected exactly once after selection.
    No sports-betting profitability claim is calculated without odds.
    """
    rows = make_rows(games)
    train, validation, test = chronological_split(rows, min_games=min_games)
    (joblib, np, LogisticRegression, _, _, _, make_pipeline, StandardScaler) = _dependencies()
    x_train, y_train = _array(train, np)
    x_val, y_val = _array(validation, np)
    x_test, y_test = _array(test, np)
    candidate = []
    for c in (0.03, 0.1, 0.3, 1.0):
        model = make_pipeline(StandardScaler(), LogisticRegression(
            C=c, max_iter=1000, random_state=42, solver="lbfgs"))
        model.fit(x_train, y_train)
        p = model.predict_proba(x_val)[:, 1]
        candidate.append((float(np.mean((p - y_val) ** 2)), c, model))
    candidate.sort(key=lambda item: (item[0], item[1]))
    _, c, winner = candidate[0]
    train_base_rate = float(y_train.mean())
    p_val = winner.predict_proba(x_val)[:, 1]
    p_test = winner.predict_proba(x_test)[:, 1]
    metrics = {
        "model": MODEL_VERSION,
        "schema": SCHEMA_VERSION,
        "source": sorted({g["source"] for g in games}),
        "selected_C": c,
        "splits": {
            "training": {"games": len(train), "through": train[-1]["date"]},
            "validation": {"games": len(validation), "from": validation[0]["date"],
                           "through": validation[-1]["date"]},
            "test": {"games": len(test), "from": test[0]["date"],
                     "through": test[-1]["date"]},
        },
        "validation": _metrics(y_val, p_val),
        "test": _metrics(y_test, p_test),
        "test_constant_baseline": _metrics(y_test, np.full(len(y_test), train_base_rate)),
        "market": "NBA moneyline only",
        "odds_available": False,
        "betting_roi_measured": False,
        "research_only": True,
        "publishing_enabled": False,
    }
    data_digest = hashlib.sha256(
        json.dumps([(g["game_id"], g["date"], g["status"], g["home_score"],
                     g["away_score"]) for g in games], sort_keys=True).encode()
    ).hexdigest()
    # Evaluate the untouched holdout once, then refit the SELECTED model
    # on every historically completed game for future *prospective* use.
    # This refit is never used to recompute the held-out test metrics.
    completed = sorted([row for row in rows if row["status"] == "final"],
                       key=lambda row: (row["date"], row["game_id"]))
    x_all, y_all = _array(completed, np)
    prospective = make_pipeline(StandardScaler(), LogisticRegression(
        C=c, max_iter=1000, random_state=42, solver="lbfgs"))
    prospective.fit(x_all, y_all)
    metrics["prospective_refit"] = {
        "games": len(completed), "through": completed[-1]["date"],
        "note": "Trained after holdout evaluation; never used to score historical test.",
    }
    bundle = {
        "model": prospective, "model_version": MODEL_VERSION,
        "feature_columns": FEATURE_COLUMNS, "schema": SCHEMA_VERSION,
        "trained_through": completed[-1]["date"], "source_hash": data_digest,
        "research_only": True, "metrics": metrics,
    }
    output = Path(artifact_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Use an atomic local artifact replacement; a failed model write cannot
    # erase a previously successful, trustworthy training result.
    temp = output.with_name(output.name + ".tmp")
    try:
        joblib.dump(bundle, temp)
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()
    return metrics


def paper_forecasts(games: list[dict], artifact_path: str | Path,
                    on_date: str, as_of: datetime | None = None) -> list[dict]:
    """Private forecasts for scheduled fixtures only (no bookmaker odds/code)."""
    joblib, np, _, _, _, _, _, _ = _dependencies()
    date.fromisoformat(on_date)
    generated_at = as_of or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("Forecast timestamp must be timezone-aware")
    generated_at = generated_at.astimezone(timezone.utc)
    bundle = joblib.load(artifact_path)  # Load only locally created, trusted artifacts.
    if (bundle.get("schema") != SCHEMA_VERSION or
            bundle.get("model_version") != MODEL_VERSION or
            not bundle.get("research_only") or
            tuple(bundle.get("feature_columns", ())) != FEATURE_COLUMNS):
        raise ValueError("Incompatible or non-research basketball model")
    if on_date <= bundle["trained_through"]:
        raise ValueError("Forecast date must be after model training cutoff")
    # Do not issue a forecast after tip-off or for an unknown start time.
    rows = [
        r for r in make_rows(games)
        if r["date"] == on_date and r["status"] == "scheduled"
        and r["start_utc"]
        and datetime.fromisoformat(str(r["start_utc"]).replace("Z", "+00:00"))
        > generated_at
    ]
    if not rows:
        return []
    x = np.asarray([r["features"] for r in rows], dtype=float)
    if not np.isfinite(x).all():
        raise ValueError("Nonfinite forecast features")
    probabilities = bundle["model"].predict_proba(x)[:, 1]
    return [{
        "game_id": r["game_id"], "date": r["date"],
        "home_team_id": r["home_id"], "away_team_id": r["away_id"],
        "home_team": r["home_name"], "away_team": r["away_name"],
        "start_utc": r["start_utc"], "generated_at": generated_at.isoformat(),
        "home_win_probability": round(float(p), 5),
        "away_win_probability": round(float(1 - p), 5),
        "model_version": MODEL_VERSION, "feature_schema": SCHEMA_VERSION,
        "research_only": True, "not_for_betting": True,
        "bookmaker_odds_verified": False, "booking_code": None,
    } for r, p in zip(rows, probabilities)]
