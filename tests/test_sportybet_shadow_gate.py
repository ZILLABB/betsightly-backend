from leagues.sportybet_shadow_gate import (
    candidate_gate,
    evaluate_staging_gate,
)


def _pick(**overrides):
    value = {
        "match_id": "shadow:1",
        "market": "over_1_5",
        "selection_probability": .72,
        "lower_reliability_bound": .68,
        "quality_score": 80.0,
        "market_trust_state": "TRUSTED",
        "market_floor_eligible": True,
        "safe_tier_eligible": True,
        "odds": 1.40,
        "odds_are_real": True,
        "bookable": True,
        "_fixture": {
            "league": "Premier League",
            "league_slug": "eng.1",
        },
    }

    value.update(
        overrides
    )

    return value


def test_candidate_gate_reuses_existing_quality_gates_without_new_score_cutoff():
    # Quality score is intentionally low-looking. This gate must not invent
    # another numerical threshold after canonical BetSightly policy already
    # decided trust, market floor and safe-tier eligibility.
    pick = _pick(
        quality_score=5.0
    )

    result = candidate_gate(
        pick
    )

    assert result["eligible"] is True
    assert result["reason_codes"] == []


def test_candidate_gate_rejects_missing_safe_tier_evidence():
    result = candidate_gate(
        _pick(
            safe_tier_eligible=False
        )
    )

    assert result["eligible"] is False

    assert (
        "SAFE_TIER_EVIDENCE_NOT_READY"
        in result["reason_codes"]
    )


def test_staging_flag_can_only_enable_review_not_merge():
    result = evaluate_staging_gate(
        [_pick()],
        board_complete=True,
        environment="staging",
        feature_flag=True,
        live_summary={
            "bookable_rate": .8,
            "selection_probability": {
                "mean": .71,
                "median": .70,
            },
            "quality_score": {
                "mean": 79.0,
                "median": 78.0,
            },
        },
        shadow_summary={
            "bookable_rate": 1.0,
            "selection_probability": {
                "mean": .72,
                "median": .72,
            },
            "quality_score": {
                "mean": 80.0,
                "median": 80.0,
            },
        },
    )

    assert (
        result["status"]
        == "ready_for_staging_review"
    )

    assert (
        result[
            "structurally_eligible_count"
        ]
        == 1
    )

    assert (
        result["staging_review_enabled"]
        is True
    )

    assert result["merge_executed"] is False
    assert result["prediction_pool_changed"] is False
    assert result["publishing_changed"] is False
    assert result["production_merge_allowed"] is False

    assert (
        result[
            "comparison_to_live"
        ]["used_as_gate"]
        is False
    )


def test_production_and_incomplete_board_are_never_merge_eligible():
    production = evaluate_staging_gate(
        [_pick()],
        board_complete=True,
        environment="production",
        feature_flag=True,
    )

    assert (
        production[
            "staging_review_enabled"
        ]
        is False
    )

    assert (
        production[
            "production_merge_allowed"
        ]
        is False
    )

    incomplete = evaluate_staging_gate(
        [_pick()],
        board_complete=False,
        environment="staging",
        feature_flag=True,
    )

    assert incomplete["status"] == "blocked"

    assert (
        incomplete[
            "staging_review_enabled"
        ]
        is False
    )

    assert incomplete["merge_executed"] is False
