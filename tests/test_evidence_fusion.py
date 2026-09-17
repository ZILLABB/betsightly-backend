from leagues.evidence_fusion import fused_market_evidence
from leagues.leg_trust import evaluate_leg_trust


def _pick(market="under_4_5", confidence=0.86, **changes):
    value = {
        "match_id": "m",
        "market": market,
        "market_group": "goals",
        "confidence": confidence,
        "raw_confidence": confidence,
        "calibration_sample": 0,
        "safe_tier_eligible": False,
        "bookable": True,
        "sportybet_availability": {
            "status": "BOOKABLE",
            "sportybet_available": True,
            "board_snapshot_id": "b",
        },
        "_fixture": {
            "commence_time": "2099-01-01T00:00:00Z",
            "league": "Premier League",
        },
    }
    value.update(changes)
    return value


def test_large_historical_evidence_can_support_low_live_market():
    decision = evaluate_leg_trust(_pick())
    assert decision["accepted"] and decision["evidence_state"] == "SUPPORTED"


def test_under_2_5_and_under_3_5_are_restricted():
    for market in ("under_2_5", "under_3_5"):
        decision = evaluate_leg_trust(_pick(market, 0.76))

        assert not decision["accepted"]
        assert decision["evidence_state"] == "SHADOW"


def test_poor_live_match_result_evidence_remains_restricted():
    evidence = fused_market_evidence(
        "home_win",
        0.67,
        "Premier League",
        {"n": 20, "actual": 0.45},
    )

    assert evidence["state"] == "SHADOW"
    assert evidence["evidence_adjusted_probability"] < 0.50
    assert evidence["live_n"] == 20


def test_btts_remains_restricted():
    decision = evaluate_leg_trust(_pick("btts_yes", 0.75))
    assert not decision["accepted"] and decision["evidence_state"] == "SHADOW"


def test_exact_bookability_is_still_required():
    decision = evaluate_leg_trust(
        _pick(
            bookable=False,
            sportybet_availability={
                "status": "SELECTION_NOT_FOUND",
                "sportybet_available": False,
            },
        )
    )
    assert not decision["accepted"]


def test_sparse_live_sample_cannot_overturn_historical_evidence():
    evidence = fused_market_evidence(
        "under_4_5", 0.86, "Premier League", {"n": 2, "actual": 0}
    )
    assert not evidence["live_conflict"]
    assert evidence["evidence_adjusted_probability"] > 0.7


def test_hierarchy_uses_league_and_confidence_bucket_when_both_are_supported():
    evidence = fused_market_evidence("under_4_5", 0.86, "Premier League", None)
    assert evidence["hierarchy_level"] == "market_league_confidence_bucket_partial_pool"


def test_hierarchy_uses_confidence_bucket_before_global_without_league_evidence():
    evidence = fused_market_evidence("under_4_5", 0.86, "unknown", None)
    assert evidence["hierarchy_level"] == "market_confidence_bucket"


def test_uncertainty_bound_reduces_ranked_probability():
    evidence = fused_market_evidence("under_4_5", 0.86, "Premier League", None)
    assert (
        evidence["lower_reliability_bound"]
        < evidence["historical_reliability_estimate"]
    )
    assert evidence["evidence_adjusted_probability"] < 0.86


def test_home_team_to_score_can_be_supported_by_replay_evidence():
    decision = evaluate_leg_trust(
        _pick(
            "home_over_0_5",
            0.78,
            market_group="team_goals_home",
        )
    )

    assert decision["accepted"]
    assert decision["evidence_state"] == "SUPPORTED"


def test_away_team_to_score_can_be_supported_by_replay_evidence():
    decision = evaluate_leg_trust(
        _pick(
            "away_over_0_5",
            0.72,
            market_group="team_goals_away",
        )
    )

    assert decision["accepted"]
    assert decision["evidence_state"] == "SUPPORTED"


def test_over_2_5_can_be_supported_by_replay_evidence():
    decision = evaluate_leg_trust(
        _pick(
            "over_2_5",
            0.70,
            market_group="goals",
        )
    )

    assert decision["accepted"]
    assert decision["evidence_state"] == "SUPPORTED"


def test_home_over_1_5_can_be_supported_by_replay_evidence():
    decision = evaluate_leg_trust(
        _pick(
            "home_over_1_5",
            0.72,
            market_group="team_goals_home",
        )
    )

    assert decision["accepted"]
    assert decision["evidence_state"] == "SUPPORTED"


def test_away_over_1_5_can_be_supported_by_replay_evidence():
    decision = evaluate_leg_trust(
        _pick(
            "away_over_1_5",
            0.72,
            market_group="team_goals_away",
            _fixture={
                "commence_time": "2099-01-01T00:00:00Z",
                "league": "unknown",
            },
        )
    )

    assert decision["accepted"]
    assert decision["evidence_state"] == "SUPPORTED"


def test_conservative_historical_calibration_is_not_treated_as_overconfidence():
    evidence = fused_market_evidence(
        "home_over_1_5",
        0.72,
        "Premier League",
        None,
    )

    assert evidence["historical_overconfidence_error"] == 0.0
    assert evidence["state"] == "SUPPORTED"


def test_promoted_market_can_still_be_rejected_by_weak_league_evidence():
    decision = evaluate_leg_trust(
        _pick(
            "away_over_1_5",
            0.72,
            market_group="team_goals_away",
        )
    )

    assert not decision["accepted"]
    assert decision["evidence_state"] == "REJECTED"
