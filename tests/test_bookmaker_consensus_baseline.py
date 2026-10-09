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
