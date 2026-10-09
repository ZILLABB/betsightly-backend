"""Independent forecast coverage is not the same as official selection."""
from leagues.forecast_coverage import coverage_funnel


def fixture(mid, kickoff="2026-10-09T12:00:00Z", *, model=True):
    return {
        "match_id": mid,
        "commence_time": kickoff,
        "_model": {
            "probabilities": {
                "home_win": .55, "draw": .25, "away_win": .20,
                "over_1_5": .82,
            }
        } if model else {},
    }


def pick(mid, *, approved=False):
    return {
        "match_id": mid,
        "market": "over_1_5",
        "market_group": "goals",
        "confidence": .80,
        "risk_adjusted_return": 1.01 if approved else .90,
        "market_floor_eligible": True,
        "safe_tier_eligible": approved,
        "market_trust_state": "TRUSTED",
        "trust": {
            "evidence_state": "PROVEN",
            "evidence_adjusted_probability": .80,
            "lower_reliability_bound": .79,
            "evidence_strength": 1.0,
            "trust_grade": "A",
            "accepted": True,
        },
        "odds": 1.4 if approved else 1.1,
        "odds_are_real": True,
        "bookable": True,
    }


def test_forecast_coverage_reports_unpublished_opinions_without_pretending_value():
    fixtures = [fixture("a"), fixture("b"), fixture("c", model=False)]
    picks = [pick("a", approved=True), pick("b")]
    report = coverage_funnel(fixtures, picks, date="2026-10-09")
    assert report["fixture_count"] == 3
    assert report["match_result_forecasts"] == 2
    assert report["fixtures_without_coherent_1x2"] == 1
    assert report["fixtures_with_any_filtered_candidate"] == 2
    assert report["fixtures_without_any_filtered_candidate"] == 1
    assert report["filtered_candidate_legs"] == 2
    assert report["real_price_candidate_legs"] == 2
    assert report["real_price_and_exact_bookable_legs"] == 2
    assert report["eligible_by_product"]["2_odds"]["approved_legs"] == 1
    assert report["eligible_by_product"]["2_odds"]["approved_unique_fixtures"] == 1
    assert report["eligible_by_product"]["2_odds"]["rejection_reasons"][
        "NEGATIVE_MODEL_VALUE"
    ] == 1
    assert report["booking_codes_created"] is False
    assert report["publication_changed"] is False


def test_wat_date_scoping_excludes_neighbouring_utc_date_and_other_picks():
    fixtures = [
        fixture("today", "2026-10-08T23:30:00Z"),
        fixture("tomorrow", "2026-10-09T23:30:00Z"),
    ]
    report = coverage_funnel(
        fixtures, [pick("today", approved=True), pick("tomorrow")],
        date="2026-10-09",
    )
    assert report["fixture_count"] == 1
    assert report["fixtures_with_any_filtered_candidate"] == 1
    assert report["eligible_by_product"]["10_odds"]["approved_legs"] == 1


def test_forecasts_are_still_counted_without_any_publishable_candidate():
    report = coverage_funnel(
        [fixture("a"), fixture("b")],
        [], date="2026-10-09",
    )
    assert report["fixtures_modelled"] == 2
    assert report["filtered_candidate_legs"] == 0
    assert report["eligible_by_product"]["banker"]["approved_legs"] == 0
