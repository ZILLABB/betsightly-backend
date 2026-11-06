"""Pure, offline favorite-side calibration guards for prospective NBA research."""
import pytest

from basketball.research_favorite_confidence import favorite_confidence_report


def record(gid, p, home_won, settled=True):
    return {"game_id": str(gid), "p": p, "y": home_won,
            "recorded_at": "2026-11-06T10:00:00+00:00" if settled else None}


def test_home_and_away_favorites_are_both_evaluated():
    r = favorite_confidence_report([
        record("away_correct", 0.2, 0),
        record("home_wrong", 0.9, 0),
        record("pending", 0.99, None, False),
    ])
    assert r["settled_forecasts_evaluated"] == 2
    assert r["pending_excluded"] == 1
    assert r["overall_predicted_winner"]["correct"] == 1
    assert r["high_confidence_70pct_plus"]["count"] == 2
    assert r["high_confidence_70pct_plus"]["observed_win_rate"] == 0.5
    assert r["favorite_ece"] is None
    assert r["largest_confidence_misses"] == [{
        "game_id": "home_wrong", "predicted_side": "home",
        "predicted_winner_confidence": 0.9,
    }]


def test_boundaries_and_prospective_review_gate():
    r = favorite_confidence_report([
        record(i, 0.6, 1) for i in range(100)
    ])
    assert r["status"] == "review_ready"
    assert r["bands"][0]["count"] == 0
    assert r["bands"][1]["count"] == 100
    assert r["bands"][1]["descriptive_only"] is False
    assert r["favorite_ece"] == 0.4
    assert r["bands"][1]["calibration_gap"] == 0.4


def test_away_favorite_at_exact_1_point_zero():
    r = favorite_confidence_report([record("certain", 0, 0)])
    assert r["bands"][-1]["count"] == 1
    assert r["overall_predicted_winner"]["correct"] == 1


def test_small_cohorts_never_claim_calibrated():
    r = favorite_confidence_report([record("a", 0.85, 1)])
    assert r["sample_size_gate_met"] is False
    assert r["high_confidence_70pct_plus"]["descriptive_only"] is True
    assert r["overall_predicted_winner"]["win_rate_95pct_ci"] is not None
    assert r["confidence_changed"] is False
    assert r["no_writes"] is True


def test_empty_cohort_is_safe():
    r = favorite_confidence_report([])
    assert r["settled_forecasts_evaluated"] == 0
    assert r["bands"][0]["observed_win_rate"] is None
    assert r["favorite_ece"] is None


@pytest.mark.parametrize("p,y", [(float("nan"), 1), (1.01, 1), (-0.1, 0), (0.6, 7)])
def test_rejects_invalid_probability_or_result(p, y):
    with pytest.raises(ValueError):
        favorite_confidence_report([record("bad", p, y)])
