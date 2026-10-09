"""Rolling challenger folds must be later, separate and never promoted."""
from datetime import date, timedelta

import pytest

from leagues.chronological_training_data import labels
from leagues.walkforward_shadow_validation import (
    evaluate_walk_forward, walk_forward_windows,
)


def sample(n_days=320, matches_per_day=2):
    rows = []
    for day_idx in range(n_days):
        day = (date(2024, 1, 1) + timedelta(days=day_idx)).isoformat()
        for fixture_idx in range(matches_per_day):
            i = 3 * day_idx + fixture_idx
            # Include all three 1X2 outcomes and both binary goal classes.
            # A fixed 4-result pattern accidentally had no draws, causing
            # intentional MISSING_OUTCOME_CLASS in the model contract.
            h, a = i % 4, (i * 5 + i // 3 + 1) % 4
            form = {
                "matches": 5, "win_rate": (i % 7) / 7,
                "draw_rate": (i % 5) / 5,
                "goals_for": (i % 9) / 3,
                "goals_against": (i % 4) / 2,
            }
            rows.append({
                "match_date": day,
                "fixture_key": f"{day}-fixture-{fixture_idx}",
                "league_slug": "eng.1" if fixture_idx else "ita.1",
                "labels": labels(h, a),
                "home_history": form,
                "away_history": dict(form, goals_against=(i % 5) / 2),
                "home_venue_history": form,
                "away_venue_history": form,
            })
    return rows


def test_four_expanding_windows_never_see_test_or_embargo_games():
    data = sample(240)
    folds = walk_forward_windows(
        list(reversed(data)), folds=4, initial_fraction=.4,
        embargo_days=7, minimum_training=50, minimum_holdout=30,
    )
    assert len(folds) == 4
    tested = set()
    prior_train_n = 0
    for train, holdout, info in folds:
        assert info["train_n"] >= prior_train_n
        prior_train_n = info["train_n"]
        assert info["train_ends"] < info["test_starts"]
        assert (date.fromisoformat(info["test_starts"]) -
                date.fromisoformat(info["train_ends"])).days >= 8
        assert not ({x["fixture_key"] for x in holdout} & tested)
        tested |= {x["fixture_key"] for x in holdout}
        assert all(
            x["match_date"] < info["test_starts"] for x in train
        )
        assert all(
            info["test_starts"] <= x["match_date"] <= info["test_ends"]
            for x in holdout
        )


def test_same_day_games_cannot_be_in_two_folds():
    folds = walk_forward_windows(
        sample(120, matches_per_day=3), folds=3,
        initial_fraction=.4, embargo_days=0,
        minimum_training=50, minimum_holdout=20,
    )
    assert len(folds) == 3
    days_per_fold = [
        {x["match_date"] for x in holdout} for _, holdout, _ in folds
    ]
    assert not (days_per_fold[0] & days_per_fold[1])
    assert not (days_per_fold[1] & days_per_fold[2])


def test_shadow_walkforward_reports_all_markets_without_champion_change():
    output = evaluate_walk_forward(sample(), folds=4)
    assert output["status"] == "WALK_FORWARD_SHADOW_EVIDENCE_ONLY"
    assert output["evaluated_folds"] == 4
    assert output["embargo_days"] == 7
    assert output["production_promotion_authorized"] is False
    assert output["champion_model_unchanged"] is True
    assert output["no_sportybet_odds_or_clv_comparison"] is True
    for market in ("match_result", "over_1_5", "over_2_5", "btts_yes"):
        result = output["markets"][market]
        assert result["evaluated_folds"] == 4
        assert 0 <= result["winning_folds"] <= 4
        assert result["test_matches"] > 0
        assert 0 <= result["weighted_challenger_brier"] <= 2


def test_rejects_invalid_fold_count_and_embargo():
    with pytest.raises(ValueError, match="folds"):
        walk_forward_windows(sample(10), folds=1)
    with pytest.raises(ValueError, match="embargo_days"):
        walk_forward_windows(sample(10), embargo_days=100)


def test_too_little_data_is_explicit_not_fabricated():
    output = evaluate_walk_forward(sample(8))
    assert output["evaluated_folds"] == 0
    assert output["markets"]["match_result"]["status"] == (
        "INSUFFICIENT_FOLD_EVIDENCE"
    )
