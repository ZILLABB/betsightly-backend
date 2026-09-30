from leagues.sportybet_shadow_evidence import (
    evaluate_evidence_snapshot_gate,
    load_evidence_snapshot,
)


def _pick(
    market="over_1_5",
    *,
    trust="TRUSTED",
):
    return {
        "match_id": "sportybet-shadow:test-1",
        "market": market,
        "selection_probability": .76,
        "lower_reliability_bound": .73,
        "quality_score": 58.0,
        "market_trust_state": trust,
        "market_floor_eligible": True,
        # The isolated staging DB is deliberately thin.
        "safe_tier_eligible": False,
        "odds": 1.30,
        "odds_are_real": True,
        "bookable": True,
        "_fixture": {
            "league": "Example League",
            "league_slug": "eng.3",
            "competition_type": "LEAGUE",
            "competition_historical_sample": 80,
        },
    }


def _snapshot(**groups):
    return {
        "version": "production-settled-v1",
        "captured_at": (
            "2026-09-30T15:00:00Z"
        ),
        "source": (
            "production_aggregate_read_only"
        ),
        "groups": groups,
    }


def test_snapshot_can_mature_market_without_mutating_original_pick():
    pick = _pick()

    result = (
        evaluate_evidence_snapshot_gate(
            [pick],
            board_complete=True,
            environment="staging",
            feature_flag=True,
            snapshot=_snapshot(
                goals_over_1_5=617,
            ),
        )
    )

    # Local staging evidence remains untouched.
    assert (
        pick["safe_tier_eligible"]
        is False
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
        result[
            "snapshot_safe_tier_candidate_count"
        ]
        == 1
    )

    assert (
        result[
            "local_safe_tier_candidate_count"
        ]
        == 0
    )

    eligible = (
        result[
            "eligible_candidates"
        ][0]
    )

    assert (
        eligible[
            "aggregate_settled_sample"
        ]
        == 617
    )

    assert (
        eligible[
            "calibration_group"
        ]
        == "goals_over_1_5"
    )

    assert result["merge_executed"] is False
    assert result["publishing_changed"] is False
    assert (
        result["production_merge_allowed"]
        is False
    )


def test_thin_snapshot_group_remains_evidence_blocked():
    result = (
        evaluate_evidence_snapshot_gate(
            [
                _pick(
                    market=(
                        "home_over_0_5"
                    )
                )
            ],
            board_complete=True,
            environment="staging",
            feature_flag=True,
            snapshot=_snapshot(
                team_goals_home=12,
            ),
        )
    )

    assert result["status"] == "blocked"

    assert (
        result[
            "structurally_eligible_count"
        ]
        == 0
    )

    assert (
        result[
            "snapshot_safe_tier_candidate_count"
        ]
        == 0
    )

    assert (
        "SAFE_TIER_EVIDENCE_NOT_READY"
        in result[
            "rejection_reason_counts"
        ]
    )


def test_snapshot_is_never_applicable_to_production():
    result = (
        evaluate_evidence_snapshot_gate(
            [_pick()],
            board_complete=True,
            environment="production",
            feature_flag=True,
            snapshot=_snapshot(
                goals_over_1_5=617,
            ),
        )
    )

    assert (
        result["status"]
        == "not_applicable_outside_staging"
    )

    assert (
        result[
            "staging_review_enabled"
        ]
        is False
    )

    assert result["merge_executed"] is False

    assert (
        result["production_merge_allowed"]
        is False
    )


def test_snapshot_parser_rejects_invalid_payload_and_cleans_counts():
    assert (
        load_evidence_snapshot(
            "not-json"
        )
        is None
    )

    parsed = load_evidence_snapshot({
        "groups": {
            "goals_over_1_5": "617",
            "bad": -1,
            "invalid": "x",
        }
    })

    assert parsed is not None

    assert parsed["groups"] == {
        "goals_over_1_5": 617,
    }
