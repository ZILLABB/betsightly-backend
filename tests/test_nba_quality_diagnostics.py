"""Regression checks for immutable NBA paper diagnostic reporting."""
import pytest

from basketball.research_quality_diagnostics import paper_quality_diagnostics


def row(gid, p, y, home=112, away=100, total=216.0, margin=8.0, settled=True):
    return {
        "game_id": str(gid),
        "fixture_date": "2026-11-01",
        "away_team": "Synthetic Away",
        "home_team": "Synthetic Home",
        "p": p,
        "y": y,
        "home_score": home if settled else None,
        "away_score": away if settled else None,
        "predicted_total": total,
        "predicted_margin": margin,
        "recorded_at": "2026-11-02T01:00:00+00:00" if settled else None,
    }


def test_misses_are_real_winners_with_sign_correct_errors():
    result = paper_quality_diagnostics([
        row("one", 0.85, 0, home=102, away=115, total=230, margin=4),
        row("two", 0.30, 0, home=104, away=106, total=205, margin=-3),
        row("pending", 0.95, None, settled=False),
    ])
    assert result["settled_count"] == 2
    assert result["pending_excluded"] == 1
    assert result["miss_count"] == 1
    miss = result["highest_confidence_misses"][0]
    assert miss["game_id"] == "one"
    assert miss["predicted_winner"] == "Synthetic Home"
    assert miss["actual_winner"] == "Synthetic Away"
    assert miss["verified_away_score"] == 115
    assert miss["verified_home_score"] == 102
    assert miss["total_points_signed_error"] == 13
    assert miss["home_margin_signed_error"] == 17
    assert result["score_projections"]["total_points"]["signed_bias"] == 4
    assert result["score_projections"]["home_margin"]["signed_bias"] == 8


def test_references_use_only_verified_settlements():
    result = paper_quality_diagnostics([
        row("a", 0.6, 1),
        row("b", 0.6, 0),
        row("c", 0.6, None, settled=False),
    ])
    assert result["baseline_winner_accuracy"]["always_home"] == 0.5
    assert result["baseline_winner_accuracy"]["always_away"] == 0.5
    assert result["baseline_winner_accuracy"]["constant_50_50_brier"] == 0.25
    assert result["score_projections"]["settled_with_both_targets"] == 2
    assert result["model_modified"] is False


def test_missing_projections_are_not_fabricated():
    result = paper_quality_diagnostics([row("a", .8, 1, total=None, margin=None)])
    assert result["score_projections"]["settled_without_targets"] == 1
    assert result["score_projections"]["total_points"]["count"] == 0
    assert result["score_projections"]["total_points"]["mae"] is None


def test_absolute_error_summary_and_percentiles():
    rows = [row(i, .8, 1, home=110, away=110, total=220+i, margin=0)
            for i in range(10)]
    result = paper_quality_diagnostics(rows)
    m = result["score_projections"]["total_points"]
    assert m["mae"] == 4.5
    assert m["median_absolute_error"] == 4.5
    assert m["p90_absolute_error"] == 8
    assert m["within_5_points"] == 0.6
    assert m["within_10_points"] == 1.0


def test_miss_sorting_and_limit():
    rows = [row(i, 0.99 - i * 0.01, 0) for i in range(20)]
    result = paper_quality_diagnostics(rows)
    assert result["miss_count"] == 20
    assert len(result["highest_confidence_misses"]) == 10
    assert result["highest_confidence_misses"][0]["game_id"] == "0"


def test_zero_settlements_do_not_divide_by_zero():
    result = paper_quality_diagnostics([])
    assert result["settled_count"] == 0
    assert result["baseline_winner_accuracy"]["always_home"] is None
    assert result["score_projections"]["total_points"]["count"] == 0


@pytest.mark.parametrize("overrides", [
    {"p": -0.2}, {"p": float("nan")}, {"y": 2},
    {"home_score": None}, {"predicted_total": 3, "predicted_margin": None},
    {"predicted_total": float("inf")},
])
def test_rejects_invalid_validated_rows(overrides):
    r = row("bad", .7, 1)
    r.update(overrides)
    with pytest.raises(ValueError):
        paper_quality_diagnostics([r])


def test_100_settlements_is_review_gate_not_model_promotion():
    result = paper_quality_diagnostics([row(i, 0.6, 1) for i in range(100)])
    assert result["status"] == "review_ready"
    assert result["sample_size_gate_met"] is True
    assert result["bookmaker_odds_verified"] is False
    assert result["betting_roi"] is None
