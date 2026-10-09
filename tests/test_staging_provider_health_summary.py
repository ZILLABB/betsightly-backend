"""ESPN failures and booking readiness must be reported separately."""
from scripts.prepare_staging_board_once import source_health_summary


def test_source_summary_distinguishes_usable_degraded_board_from_complete_provider():
    source = source_health_summary({
        "ready": True,
        "complete": False,
        "provider": {
            "complete": False,
            "requested_league_count": 116,
            "successful_league_count": 99,
            "failed_leagues": ["ukr.1", "alg.1", "ukr.1"],
            "failed_league_details": {
                "alg.1": {"error": "202610: HTTP 400", "failed_months": ["202610"]},
                "ukr.1": {"error": "HTTP 400", "failed_months": ["202610"]},
            },
            "recovered_leagues": ["alg.1"],
        },
    })
    assert source["board_ready_independent_of_provider_completeness"] is True
    assert source["espn_complete"] is False
    assert source["espn_leagues_requested"] == 116
    assert source["espn_leagues_succeeded"] == 99
    assert source["espn_leagues_failed"] == 2
    assert source["espn_failed_leagues"] == ["alg.1", "ukr.1"]
    assert source["espn_failed_reasons"]["alg.1"]["error"] == "202610: HTTP 400"
    assert source["espn_previous_snapshot_recovered_leagues"] == ["alg.1"]


def test_source_summary_is_fail_closed_without_provider_details():
    source = source_health_summary({"ready": False})
    assert source["board_ready_independent_of_provider_completeness"] is False
    assert source["espn_complete"] is False
    assert source["espn_failed_leagues"] == []
