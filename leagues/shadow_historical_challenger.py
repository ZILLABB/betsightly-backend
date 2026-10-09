"""Never-promoted offline shadow evaluation of true historical match data.

Uses chronological held-out matches, not randomized train/test leakage.
The source is CC0 and presently single-source; pass independent result
verification before shipping any fitted coefficients to the public engine.
"""
from __future__ import annotations

from collections import Counter

FEATURES = ("home_history", "away_history",
            "home_venue_history", "away_venue_history")
FIELDS = ("matches", "win_rate", "draw_rate", "goals_for", "goals_against")
BINARY_MARKETS = ("over_1_5", "over_2_5", "btts_yes")


def feature_vector(example: dict) -> list[float]:
    values = []
    for name in FEATURES:
        group = example.get(name) or {}
        for field in FIELDS:
            value = group.get(field)
            values.extend((
                float(value) if value is not None else 0.0,
                1.0 if value is None else 0.0,
            ))
    return values


def _binary_brier(probabilities, labels) -> float:
    return sum(
        (float(p) - int(y)) ** 2 for p, y in zip(probabilities, labels)
    ) / len(labels)


def evaluate_shadow(train: list[dict], holdout: list[dict], *,
                    min_training: int = 200,
                    min_holdout: int = 50) -> dict:
    if len(train) < min_training or len(holdout) < min_holdout:
        return {
            "status": "INSUFFICIENT_CHRONOLOGICAL_EVIDENCE",
            "training_matches": len(train), "holdout_matches": len(holdout),
            "minimum_training": min_training, "minimum_holdout": min_holdout,
            "champion_model_unchanged": True,
        }
    if max(row["match_date"] for row in train) >= min(
        row["match_date"] for row in holdout
    ):
        raise ValueError("Historical leakage: train and holdout dates overlap")

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    x_train = np.asarray([feature_vector(x) for x in train], dtype=float)
    x_holdout = np.asarray([feature_vector(x) for x in holdout], dtype=float)
    report = {}
    for market in BINARY_MARKETS:
        train_labels = np.asarray([
            int(x["labels"][market]) for x in train
        ], dtype=int)
        holdout_labels = np.asarray([
            int(x["labels"][market]) for x in holdout
        ], dtype=int)
        if len(set(train_labels)) < 2:
            report[market] = {"status": "SINGLE_CLASS_IN_TRAINING"}
            continue
        champion = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=400, C=.25, random_state=17),
        )
        champion.fit(x_train, train_labels)
        preds = champion.predict_proba(x_holdout)[:, 1]
        baseline = float(train_labels.mean())
        model_score = _binary_brier(preds, holdout_labels)
        naive_score = _binary_brier(
            [baseline] * len(holdout_labels), holdout_labels
        )
        report[market] = {
            "status": "SHADOW_EVALUATED",
            "holdout_brier": round(model_score, 6),
            "training_base_rate_brier": round(naive_score, 6),
            "beats_trailing_training_base_rate": bool(model_score < naive_score),
            "training_base_rate": round(baseline, 6),
            "holdout_hit_frequency": round(float(holdout_labels.mean()), 6),
            "holdout_n": len(holdout_labels),
        }

    # 1X2 is a coherent multinomial: probabilities always sum to one.
    class_keys = ("home_win", "draw", "away_win")
    train_classes = np.asarray([
        next((i for i, key in enumerate(class_keys) if x["labels"][key]), -1)
        for x in train
    ], dtype=int)
    test_classes = np.asarray([
        next((i for i, key in enumerate(class_keys) if x["labels"][key]), -1)
        for x in holdout
    ], dtype=int)
    if (min(train_classes) < 0 or min(test_classes) < 0):
        raise ValueError("Incoherent 1X2 labels in training results")
    if len(set(train_classes)) < 3:
        report["match_result"] = {"status": "MISSING_OUTCOME_CLASS"}
    else:
        predictor = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=400, C=.25, random_state=17),
        )
        predictor.fit(x_train, train_classes)
        probabilities = predictor.predict_proba(x_holdout)
        class_probabilities = np.zeros((len(holdout), 3), dtype=float)
        for column, label in enumerate(predictor.classes_):
            class_probabilities[:, int(label)] = probabilities[:, column]
        priors = np.bincount(train_classes, minlength=3).astype(float)
        priors /= priors.sum()
        actual = np.eye(3)[test_classes]
        brier = float(np.mean(np.sum(
            (class_probabilities - actual) ** 2, axis=1
        )))
        naive = float(np.mean(np.sum((priors - actual) ** 2, axis=1)))
        report["match_result"] = {
            "status": "SHADOW_EVALUATED",
            "holdout_multiclass_brier": round(brier, 6),
            "training_base_rate_brier": round(naive, 6),
            "beats_trailing_training_base_rate": bool(brier < naive),
            "holdout_n": len(holdout),
            "probabilities_coherent": bool(np.allclose(
                class_probabilities.sum(axis=1), 1.0,
            )),
        }

    return {
        "status": "SHADOW_EVALUATION_ONLY",
        "training_matches": len(train),
        "holdout_matches": len(holdout),
        "holdout_started": min(x["match_date"] for x in holdout),
        "baseline_comparison": report,
        "source_verified_independently": False,
        "champion_model_unchanged": True,
        "publishing_changed": False,
    }
