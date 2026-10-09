"""Paired historical evaluations must expose uncertainty and per-league drift."""
from datetime import date, timedelta

import pytest

from leagues.shadow_historical_challenger import (
    evaluate_shadow, paired_loss_diagnostics,
)
from tests.test_shadow_historical_challenger import example


def test_paired_score_reports_unseen_dates_and_each_sufficient_league():
    examples = [
        {
            "match_date": (date(2026, 3, 1) + timedelta(days=i)).isoformat(),
            "league_slug": "eng.1" if i < 40 else "fra.1",
        } for i in range(80)
    ]
    result = paired_loss_diagnostics(
        examples, [0.1] * 80, [0.3] * 80,
    )
    assert result["overall"]["n"] == 80
    assert result["overall"]["paired_improvement"] == 0.2
    assert result["nominal_interval_excludes_zero"] is True
    assert result["latest_90_days"]["n"] == 80
    assert result["league_count_with_enough_matches"] == 2
    assert result["per_league_minimum_30_games"]["fra.1"]["n"] == 40
    assert result["production_promotion_authorized"] is False
    assert result["market_odds_comparison_available"] is False
    assert result["champion_model_comparison_available"] is False
    assert result["independent_fixture_assumption_unproven"] is True


def test_small_league_not_reported_as_statistically_supported():
    rows = [
        {"match_date": "2026-08-01", "league_slug": "sco.1"}
        for _ in range(5)
    ]
    result = paired_loss_diagnostics(
        rows, [0.3] * 5, [0.25] * 5,
    )
    assert result["overall"]["model_better"] is False
    assert result["nominal_interval_excludes_zero"] is False
    assert result["league_count_with_enough_matches"] == 0


def test_inconsistent_paired_lengths_are_not_scored():
    with pytest.raises(ValueError, match="identical"):
        paired_loss_diagnostics(
            [{"match_date": "2026-01-01", "league_slug": "eng.1"}],
            [0.1], [],
        )


def test_shadow_evaluation_includes_diagnostics_but_no_promotion():
    report = evaluate_shadow(
        [example(i) for i in range(220)],
        [example(i) for i in range(220, 290)],
    )
    assert report["status"] == "SHADOW_EVALUATION_ONLY"
    assert report["production_promotion_authorized"] is False
    assert report["evaluation_limitations"]
    for key in ("over_1_5", "over_2_5", "btts_yes", "match_result"):
        market = report["baseline_comparison"][key]
        assert market["paired_diagnostics"]["overall"]["n"] == 70
        assert market["paired_diagnostics"]["production_promotion_authorized"] is False
        assert market["paired_diagnostics"]["overall"]["model_brier"] >= 0
