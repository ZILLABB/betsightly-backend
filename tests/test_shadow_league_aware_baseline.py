"""Train-only league priors are a stronger baseline than pooled match rates."""
from datetime import date, timedelta

import pytest

from leagues.shadow_historical_challenger import (
    evaluate_shadow, league_conditional_training_probs,
)


def row(day, league, label, idx=0):
    return {
        "match_date": day,
        "fixture_key": f"{day}:{league}:{idx}",
        "league_slug": league,
        "labels": {"home_win": int(label == 0), "draw": int(label == 1),
                   "away_win": int(label == 2),
                   "over_1_5": int(label != 1),
                   "over_2_5": int(label == 0),
                   "btts_yes": int(label != 0)},
        "home_history": {
            "matches": 5, "win_rate": idx % 5 / 5,
            "draw_rate": .15, "goals_for": 1.4, "goals_against": 1.1,
        },
        "away_history": {
            "matches": 5, "win_rate": (idx + 1) % 5 / 5,
            "draw_rate": .2, "goals_for": 1.2, "goals_against": 1.2,
        },
        "home_venue_history": {"matches": 2, "goals_for": 1},
        "away_venue_history": {"matches": 2, "goals_for": 1},
    }


def test_league_prior_uses_train_only_with_smoothing_and_unseen_fallback():
    train = [
        row("2024-01-01", "eng.1", 0),
        row("2024-01-02", "eng.1", 0),
        row("2024-01-03", "fra.1", 2),
        row("2024-01-04", "fra.1", 1),
    ]
    outcomes = [0, 0, 2, 1]
    holdout = [
        row("2024-04-01", "eng.1", 2),
        row("2024-04-02", "fra.1", 0),
        row("2024-04-03", "usa.1", 1),
    ]
    probs = league_conditional_training_probs(
        train, holdout, outcomes, class_count=3, prior_strength=2,
    )
    assert probs[0] == pytest.approx([.75, .125, .125])
    assert probs[1] == pytest.approx([.25, .375, .375])
    assert probs[2] == pytest.approx([.5, .25, .25])
    assert all(sum(p) == pytest.approx(1.0) for p in probs)
    # Changing held-out labels cannot modify forecasts.
    holdout[0]["labels"] = row("2024-04-01", "eng.1", 1)["labels"]
    assert league_conditional_training_probs(
        train, holdout, outcomes, class_count=3, prior_strength=2,
    ) == probs


def test_invalid_or_mismatched_training_classes_fail_closed():
    with pytest.raises(ValueError, match="same training fixtures"):
        league_conditional_training_probs(
            [row("2024-01-01", "eng.1", 0)], [], [], class_count=2,
        )
    with pytest.raises(ValueError, match="Invalid training outcome"):
        league_conditional_training_probs(
            [row("2024-01-01", "eng.1", 0)], [], [4], class_count=2,
        )


def test_all_markets_report_harder_league_baseline_no_promotion():
    start = date(2024, 1, 1)
    train = [
        row((start + timedelta(days=i)).isoformat(),
            "eng.1" if i % 2 else "fra.1", i % 3, i)
        for i in range(210)
    ]
    holdout = [
        row((start + timedelta(days=i)).isoformat(),
            "eng.1" if i % 2 else "fra.1", i % 3, i)
        for i in range(220, 280)
    ]
    result = evaluate_shadow(train, holdout)
    assert result["status"] == "SHADOW_EVALUATION_ONLY"
    assert result["champion_model_unchanged"] is True
    assert result["production_promotion_authorized"] is False
    for market in ("match_result", "over_1_5", "over_2_5", "btts_yes"):
        item = result["baseline_comparison"][market]
        assert item["status"] == "SHADOW_EVALUATED"
        assert item["league_conditional_baseline_brier"] >= 0
        assert item["paired_vs_league_conditional_baseline"]["overall"]["n"] == 60
        assert item["paired_vs_league_conditional_baseline"][
            "champion_model_comparison_available"
        ] is False
