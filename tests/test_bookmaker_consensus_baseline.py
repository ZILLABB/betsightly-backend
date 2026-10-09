"""Basic three-way baseline is separate from the prediction model."""
from datetime import datetime, timezone

from leagues.bookmaker_consensus_baseline import (
    devig_market, fixture_consensus, full_day_baseline,
)


def fixture(event_id="event-1", *, odds=None, name="Real fixture"):
    kickoff = datetime(2026, 10, 9, 18, tzinfo=timezone.utc)
    return {
        "event_id": event_id, "home_team": name, "away_team": "Opponents FC",
        "kickoff_ms": int(kickoff.timestamp() * 1000),
        "competition": "Premier League",
        "prices": odds or {
            "home_win": 1.5, "draw": 4, "away_win": 6.0,
            "over_1_5": 1.2, "under_1_5": 4.5,
        },
    }


def test_price_distribution_sums_to_one_and_has_margin():
    result = devig_market(
        {"home_win": 1.5, "draw": 4, "away_win": 6},
        ("home_win", "draw", "away_win"),
    )
    assert result["bookmaker_overround"] > 0
    assert abs(sum(result["probabilities"].values()) - 1) < 0.00001
    assert result["probabilities"]["home_win"] > .6


def test_baseline_never_claims_stakeable_independent_prediction():
    prediction = fixture_consensus(fixture(), date_wat="2026-10-09")
    assert prediction["status"] == "MARKET_BASELINE_ONLY"
    assert prediction["most_likely_outcome"] == "home_win"
    assert prediction["officially_publishable"] is False
    assert prediction["forecast_kind"] == "BOOKMAKER_CONSENSUS_NOT_INDEPENDENT_MODEL"
    assert prediction["bookmaker_booking_validated"] is False


def test_simulated_fixture_is_not_treated_as_real_match():
    fake = fixture(name="Team SRL")
    report = fixture_consensus(fake, date_wat="2026-10-09")
    assert report["status"] == "SIMULATED_EXCLUDED"


def test_missing_complete_three_way_prices_returns_explicit_abstention():
    bad = fixture(odds={"home_win": 1.5, "draw": 4})
    assert fixture_consensus(bad, date_wat="2026-10-09")["status"] == "INSUFFICIENT_REAL_ODDS"
    assert devig_market(
        {"home_win": 0, "draw": 4, "away_win": 5},
        ("home_win", "draw", "away_win"),
    ) is None


def test_every_cached_unique_fixture_gets_a_review_row():
    report = full_day_baseline({
        "one": [fixture("m1"), fixture("m2", name="Club SRL")],
        "two": [fixture("m1"), fixture("m3")],
    }, date_wat="2026-10-09")
    assert report["count"] == 3
    assert report["pre_match_forecasts"] == 2
    assert report["statuses"]["SIMULATED_EXCLUDED"] == 1
    assert report["official_predictions_changed"] is False


def test_out_of_day_youth_and_simulated_are_excluded_before_classifying_today():
    today = fixture("today")
    tomorrow = fixture("tomorrow", name="Club SRL")
    tomorrow["kickoff_ms"] += 24 * 60 * 60 * 1000
    tomorrow_youth = fixture("tomorrow-youth")
    tomorrow_youth["kickoff_ms"] += 24 * 60 * 60 * 1000
    tomorrow_youth["home_squad"] = "U19"
    today_youth = fixture("youth")
    today_youth["home_squad"] = "U19"
    today_srl = fixture("srl", name="Club SRL")
    board = {"all": [today, tomorrow, tomorrow_youth, today_youth, today_srl]}
    report = full_day_baseline(board, date_wat="2026-10-09")
    assert report["count"] == 3
    assert report["statuses"] == {
        "MARKET_BASELINE_ONLY": 1,
        "NON_SENIOR_EXCLUDED": 1,
        "SIMULATED_EXCLUDED": 1,
    }
    assert all(entry["date_wat"] == "2026-10-09" for entry in report["full_day_fixtures"])
    assert {entry["event_id"] for entry in report["full_day_fixtures"]} == {
        "today", "youth", "srl",
    }


def test_wrong_day_precedes_identity_error():
    tomorrow_invalid_identity = fixture("tomorrow", name="Opponents FC")
    tomorrow_invalid_identity["kickoff_ms"] += 24 * 60 * 60 * 1000
    assert fixture_consensus(
        tomorrow_invalid_identity, date_wat="2026-10-09"
    )["status"] == "WRONG_WAT_DAY"


def test_outside_date_duplicate_cannot_mask_requested_day_fixture():
    # Some bookmaker snapshots may contain event IDs grouped more than once.
    wrong_day = fixture("match-1", name="Other Day Club SRL")
    wrong_day["kickoff_ms"] += 24 * 60 * 60 * 1000
    today = fixture("match-1", name="Real Club")
    result = full_day_baseline(
        {"first": [wrong_day], "second": [today]},
        date_wat="2026-10-09",
    )
    assert result["count"] == 1
    assert result["pre_match_forecasts"] == 1
    assert result["full_day_fixtures"][0]["home_team"] == "Real Club"
