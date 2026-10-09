"""Never-promoted offline shadow evaluation of true historical match data.

Uses chronological held-out matches, not randomized train/test leakage.
The source is CC0 and presently single-source; pass independent result
verification before shipping any fitted coefficients to the public engine.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import sqrt

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


def paired_loss_diagnostics(
    examples: list[dict], model_losses: list[float],
    baseline_losses: list[float], *, minimum_league_n: int = 30,
) -> dict:
    """Track improvement and uncertainty on the SAME later fixtures.

    Report a descriptive independent-match normal interval only; games from
    the same league/day are dependent so this is NOT production evidence.
    Source, champion and bookmaker comparisons are separate requirements.
    """
    if not (len(examples) == len(model_losses) == len(baseline_losses)):
        raise ValueError("Paired scoring must use identical held-out fixtures")
    if not examples:
        return {"status": "NO_HOLDOUT"}
    deltas = [float(base) - float(model)
              for model, base in zip(model_losses, baseline_losses)]

    def sample(indices: list[int]) -> dict:
        n = len(indices)
        if not n:
            return {"n": 0, "status": "NO_EVIDENCE"}
        difference = sum(deltas[i] for i in indices) / n
        model_avg = sum(float(model_losses[i]) for i in indices) / n
        base_avg = sum(float(baseline_losses[i]) for i in indices) / n
        if n > 1:
            variance = sum(
                (deltas[i] - difference) ** 2 for i in indices
            ) / (n - 1)
            half_width = 1.96 * sqrt(variance / n)
        else:
            half_width = None
        return {
            "n": n,
            "model_brier": round(model_avg, 6),
            "baseline_brier": round(base_avg, 6),
            "paired_improvement": round(difference, 6),
            "model_better": bool(difference > 0),
            "nominal_95pct_ci": (
                [round(difference - half_width, 6),
                 round(difference + half_width, 6)]
                if half_width is not None else None
            ),
        }

    latest = max(date.fromisoformat(x["match_date"]) for x in examples)
    cutoff = latest - timedelta(days=90)
    recent = [
        i for i, row in enumerate(examples)
        if date.fromisoformat(row["match_date"]) >= cutoff
    ]
    leagues: dict[str, list[int]] = defaultdict(list)
    for i, example in enumerate(examples):
        leagues[str(example.get("league_slug") or "unknown")].append(i)
    per_league = {
        slug: sample(indices) for slug, indices in sorted(leagues.items())
        if len(indices) >= minimum_league_n
    }
    overall = sample(list(range(len(examples))))
    lower = overall["nominal_95pct_ci"]
    return {
        "overall": overall,
        "latest_90_days": {
            "from": cutoff.isoformat(),
            "through": latest.isoformat(),
            **sample(recent),
        },
        "per_league_minimum_30_games": per_league,
        "league_count_in_holdout": len(leagues),
        "league_count_with_enough_matches": len(per_league),
        "nominal_interval_excludes_zero": bool(lower and lower[0] > 0),
        "independent_fixture_assumption_unproven": True,
        "market_odds_comparison_available": False,
        "champion_model_comparison_available": False,
        "production_promotion_authorized": False,
    }


def league_conditional_training_probs(
    train: list[dict], holdout: list[dict],
    train_classes: list[int], *, class_count: int,
    prior_strength: float = 20.0,
) -> list[list[float]]:
    """Train-only league rates with an empirical-Bayes global fallback.

    An unseen league gets the pooled training distribution. Small leagues
    shrink toward that distribution, avoiding extreme 0%/100% estimates.
    This does not use results from the holdout, odds, or future matches.
    """
    if len(train) != len(train_classes):
        raise ValueError("League priors must have the same training fixtures")
    if not train or not class_count > 1 or prior_strength < 0:
        raise ValueError("Invalid league-prior training inputs")
    if any(type(y) is not int or not 0 <= y < class_count
           for y in train_classes):
        raise ValueError("Invalid training outcome class")

    global_counts = [0] * class_count
    league_counts: dict[str, list[int]] = {}
    for example, label in zip(train, train_classes):
        global_counts[label] += 1
        league = str(example.get("league_slug") or "UNKNOWN")
        counts = league_counts.setdefault(league, [0] * class_count)
        counts[label] += 1
    global_probs = [count / len(train) for count in global_counts]
    result = []
    for row in holdout:
        league = str(row.get("league_slug") or "UNKNOWN")
        counts = league_counts.get(league, [0] * class_count)
        n = sum(counts)
        weights = [
            (count + prior_strength * global_probs[i])
            / (n + prior_strength) if n + prior_strength else global_probs[i]
            for i, count in enumerate(counts)
        ]
        result.append(weights)
    return result


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
        model_losses = [(float(p) - int(y)) ** 2
                        for p, y in zip(preds, holdout_labels)]
        baseline_losses = [(baseline - int(y)) ** 2
                           for y in holdout_labels]
        league_probs = league_conditional_training_probs(
            train, holdout, [int(y) for y in train_labels],
            class_count=2,
        )
        league_losses = [
            (row[1] - int(y)) ** 2
            for row, y in zip(league_probs, holdout_labels)
        ]
        report[market] = {
            "league_conditional_baseline_brier": round(
                sum(league_losses) / len(holdout_labels), 6,
            ),
            "beats_league_conditional_baseline": bool(
                sum(model_losses) < sum(league_losses)
            ),
            "paired_vs_league_conditional_baseline": paired_loss_diagnostics(
                holdout, model_losses, league_losses,
            ),
            "paired_diagnostics": paired_loss_diagnostics(
                holdout, model_losses, baseline_losses,
            ),
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
        per_match_model_losses = np.sum(
            (class_probabilities - actual) ** 2, axis=1
        ).tolist()
        per_match_baseline_losses = np.sum(
            (priors - actual) ** 2, axis=1
        ).tolist()
        league_probs = np.asarray(league_conditional_training_probs(
            train, holdout, [int(x) for x in train_classes],
            class_count=3,
        ), dtype=float)
        league_losses = np.sum(
            (league_probs - actual) ** 2, axis=1
        ).tolist()
        report["match_result"] = {
            "league_conditional_baseline_brier": round(
                sum(league_losses) / len(holdout), 6,
            ),
            "beats_league_conditional_baseline": bool(
                sum(per_match_model_losses) < sum(league_losses)
            ),
            "paired_vs_league_conditional_baseline": paired_loss_diagnostics(
                holdout, per_match_model_losses, league_losses,
            ),
            "paired_diagnostics": paired_loss_diagnostics(
                holdout, per_match_model_losses,
                per_match_baseline_losses,
            ),
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
        "production_promotion_authorized": False,
        "evaluation_limitations": [
            "Single chronological split, not rolling forward cross-validation",
            "Pooled and smoothed training-league baselines; neither is the production champion",
            "No paired bookmaker odds or closing-line value evaluation",
            "Sources not independently verified",
        ],
    }
