"""Shadow challenger never mutates champion and uses future unseen dates."""
from datetime import date, timedelta

import pytest

from leagues.shadow_historical_challenger import (
    evaluate_shadow, feature_vector,
)
from leagues.chronological_training_data import labels


def example(i):
    played = date(2024, 1, 1) + timedelta(days=i)
    home_goals = (i * 7) % 4
    away_goals = (i * 3 + 1) % 3
    form = {
        "matches": 5, "win_rate": (i % 4) / 5,
        "draw_rate": .2, "goals_for": (i % 5) / 2,
        "goals_against": (i % 3) / 2,
    }
    return {
        "match_date": played.isoformat(),
        "labels": labels(home_goals, away_goals),
        "home_history": form,
        "away_history": dict(form, win_rate=1 - form["win_rate"]),
        "home_venue_history": form,
        "away_venue_history": dict(form, goals_for=.3),
    }


def test_insufficient_rows_do_not_train_or_publish():
    report = evaluate_shadow([example(i) for i in range(15)], [])
    assert report["status"] == "INSUFFICIENT_CHRONOLOGICAL_EVIDENCE"
    assert report["champion_model_unchanged"] is True


def test_disjoint_chronological_holdout_is_scored_not_promoted():
    report = evaluate_shadow(
        [example(i) for i in range(220)],
        [example(i) for i in range(220, 290)],
    )
    assert report["status"] == "SHADOW_EVALUATION_ONLY"
    assert report["champion_model_unchanged"] is True
    assert report["publishing_changed"] is False
    assert report["source_verified_independently"] is False
    for market in ("over_1_5", "over_2_5", "btts_yes"):
        assert report["baseline_comparison"][market]["status"] == "SHADOW_EVALUATED"
    assert report["baseline_comparison"]["match_result"]["probabilities_coherent"] is True


def test_overlap_or_reverse_order_rejected():
    with pytest.raises(ValueError, match="leakage"):
        evaluate_shadow(
            [example(i) for i in range(220)],
            [example(i) for i in range(200, 270)],
        )


def test_features_do_not_use_labels_as_predictors():
    case = example(5)
    features = feature_vector(case)
    assert len(features) == 40
    case["labels"] = labels(15, 0)
    assert feature_vector(case) == features
