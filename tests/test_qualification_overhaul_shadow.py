"""Adversarial offline tests: no bookmaker access or live database required."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from leagues.qualification_overhaul_shadow import (
    _score_market,
    compare_market_penalties,
    independent_tier_exposure,
    score_complete_forecast_pool,
    settlement_queue_audit,
)


def _inputs(market="over_1_5", *, eligible=False):
    snapshot = {
        "snapshot_id": "frozen-sha256", "generated_at": "2026-10-26T06:00:00Z",
        "candidates": [{
            "fixture_id": "fixture-10", "league_slug": "esp.copa_del_rey",
            "market": market, "kickoff": "2026-10-26T18:00:00Z",
            "calibrated_probability": .78, "conservative_probability": .65,
            "bookmaker_implied_probability": .60, "odds": 1.80,
            "odds_source": "SportyBet", "bookable": True,
            "safe_tier_eligible": eligible, "trust_grade": "B",
            "competition_type": "DOMESTIC_CUP",
        }],
    }
    final = {
        "fixture_id": "fixture-10", "league_slug": "esp.copa_del_rey",
        "kickoff": "2026-10-26T18:00:00Z",
        "status": "FINAL", "period": "REGULATION",
        "verified": True, "source": "IndependentScoreFeed",
        "source_event_id": "source-100", "verified_at": "2026-10-26T20:30:00Z",
        "home_score": 2, "away_score": 1,
    }
    return snapshot, final


def test_every_pregame_market_is_scored_even_if_rejected_from_official_tier():
    snapshot, final = _inputs()
    result = score_complete_forecast_pool([snapshot], [final])
    assert result["settled_unique_forecasts"] == 1
    row = result["observations"][0]
    assert row["outcome"] == 1
    assert row["originally_official_eligible"] is False
    assert row["conservative_probability"] == .65
    assert row["snapshot_id"] == "frozen-sha256"
    assert result["upstream_score_verification_required"] is True


def test_repeated_products_and_snapshot_replays_do_not_inflate_sample():
    first, final = _inputs()
    second = deepcopy(first)
    second["snapshot_id"] = "later"
    second["generated_at"] = "2026-10-26T07:00:00Z"
    second["candidates"][0]["calibrated_probability"] = .97
    result = score_complete_forecast_pool([second, first, first], [final])
    assert result["unique_pre_match_forecasts"] == 1
    assert result["observations"][0]["calibrated_probability"] == .78


def test_post_kickoff_and_unverified_scores_are_never_learned_as_truth():
    first, final = _inputs()
    first["generated_at"] = "2026-10-26T18:00:00Z"
    assert score_complete_forecast_pool([first], [final])["settled_unique_forecasts"] == 0

    first["generated_at"] = "2026-10-26T06:00:00Z"
    final["verified"] = False
    report = score_complete_forecast_pool([first], [final])
    assert report["settled_unique_forecasts"] == 0
    assert report["pending_or_excluded"]["unverified_or_nonregulation_final"] == 1


def test_kickoff_move_and_cross_league_finals_are_not_reassigned():
    first, final = _inputs()
    final["kickoff"] = "2026-10-27T18:00:00Z"
    assert score_complete_forecast_pool([first], [final])["pending_or_excluded"]["kickoff_identity_mismatch"] == 1
    final["kickoff"] = "2026-10-26T18:00:00Z"
    final["league_slug"] = "eng.fa_cup"
    assert score_complete_forecast_pool([first], [final])["settled_unique_forecasts"] == 0


def test_duplicate_verified_finals_quarantined_even_when_scores_match():
    first, final = _inputs()
    report = score_complete_forecast_pool([first], [final, deepcopy(final)])
    assert report["settled_unique_forecasts"] == 0
    assert report["pending_or_excluded"]["ambiguous_final"] == 1


def test_dnb_draw_is_push_and_score_market_covers_cup_regulation():
    first, final = _inputs("dnb_home")
    final["home_score"] = final["away_score"] = 1
    report = score_complete_forecast_pool([first], [final])
    assert report["settled_unique_forecasts"] == 0
    assert report["pending_or_excluded"]["unsupported_market_or_push"] == 1
    assert _score_market(2, 1, "btts_yes") == 1
    assert _score_market(2, 1, "away_over_1_5") == 0
    assert _score_market(2, 1, "over_2_5") == 1
    assert _score_market(2, 1, "under_3_5") == 1
    assert _score_market(0, 0, "home_or_away") == 0
    assert _score_market(2, 1, "unknown_market") is None


def test_penalty_review_is_read_only_and_low_sample_does_not_promote():
    snapshot, final = _inputs()
    rows = score_complete_forecast_pool([snapshot], [final])["observations"]
    report = compare_market_penalties(rows)
    market = report["markets"]["over_1_5"]
    assert market["ready_for_review"] is False
    assert market["action"] == "COLLECT_MORE_VERIFIED_LABELS"
    assert report["automatic_promotion"] is False
    assert market["methods"]["half_relaxation"]["n"] == 0


def test_chronological_holdout_excludes_earlier_days():
    rows = []
    for day in range(20):
        kickoff = (datetime(2026, 9, 1, tzinfo=timezone.utc)
                   + timedelta(days=day)).isoformat()
        for i in range(15):
            rows.append({
                "fixture_id": f"{day}-{i}", "market": "btts_yes",
                "kickoff": kickoff, "calibrated_probability": .7,
                "conservative_probability": .6, "outcome": (day + i) % 2,
                "bookable": True, "odds": 1.8,
            })
    report = compare_market_penalties(rows)["markets"]["btts_yes"]
    assert report["ready_for_review"] is True
    assert report["holdout_days"] == 8
    assert report["methods"]["baseline"]["n"] == 120
    assert report["methods"]["half_relaxation"]["n"] == 120


def test_cross_tier_exposure_is_measured_without_publishing_or_inventing_replacements():
    legs = {
        "banker": [{"fixture_id": "x"}],
        "5_odds": [{"fixture_id": "x"}, {"fixture_id": "y"}],
        "10_odds": [{"fixture_id": "x"}, {"fixture_id": "z"}],
        "over_1_5": [{"fixture_id": "w"}],
    }
    report = independent_tier_exposure(legs)
    assert report["cross_tier_shared_fixtures"]["x"] == 3
    assert report["capacity_shadow"]["1"]["excess_fixture_uses"] == 2
    assert report["capacity_shadow"]["2"]["excess_fixture_uses"] == 1
    assert report["official_booking_verified"] is False


def test_queue_audit_never_changes_pending_to_won_or_lost():
    queue = {"total_pending_legs": 90, "overdue_48h": 90,
             "legs": [
                 {"overdue_48h": True, "review_category": "source_unsupported"},
                 {"overdue_48h": True, "review_category": "country_unknown"},
             ]}
    original = deepcopy(queue)
    result = settlement_queue_audit(queue)
    assert queue == original
    assert result["reported_overdue_48h"] == 90
    assert result["returned_overdue_48h"] == 2
    assert result["unmapped_or_unknown"] == 2
    assert result["truncated"] is True
    assert result["mode"] == "READ_ONLY_NO_SETTLEMENT"
