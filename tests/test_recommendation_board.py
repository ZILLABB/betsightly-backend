from leagues.recommendation_board import (
    build_recommendation_board,
    recommendation_classification,
)


def _fixture(match_id="f1", kickoff="2026-09-10T18:00:00Z"):
    return {
        "match_id": match_id, "commence_time": kickoff,
        "home": {"name": f"Home {match_id}", "logo": None},
        "away": {"name": f"Away {match_id}", "logo": None},
        "league": "Test League", "league_slug": "test.league",
    }


def _pick(market="over_1_5", confidence=.72, *, fixture=None, odds=1.35,
          state="SUPPORTED", evidence_strength=.9):
    fixture = fixture or _fixture()
    return {
        "match_id": fixture["match_id"], "market": market,
        "market_group": "goals", "prediction": market,
        "confidence": confidence, "raw_confidence": confidence,
        "odds": odds, "odds_are_real": True,
        "odds_provider": "SportyBet", "bookable": True,
        "expected_value": min(.10, confidence * odds - 1),
        "market_implied_probability": confidence - .01,
        "ml_confidence": confidence - .01,
        "safe_tier_eligible": True,
        "calibration_group": market, "calibration_sample": 50,
        "trust": {
            "evidence_state": state,
            "evidence_strength": evidence_strength,
            "evidence_adjusted_probability": confidence,
            "lower_reliability_bound": confidence - .03,
            "trust_grade": "A",
        },
        "_fixture": fixture,
        "_model": {
            "expected_goals": {"home": 1.4, "away": 1.2, "total": 2.6},
            "probabilities": {"draw": .25}, "has_market": True,
        },
        "edge": .01,
    }


def test_board_returns_one_best_pick_and_ranked_alternatives_per_fixture():
    fixture = _fixture()
    result = build_recommendation_board([
        _pick("over_1_5", .76, fixture=fixture),
        _pick("under_4_5", .72, fixture=fixture, odds=1.55),
    ], [fixture], date="2026-09-10")

    assert result["summary"]["fixtures_analysed"] == 1
    assert result["summary"]["recommendations"] == 1
    recommendation = result["recommendations"][0]
    assert recommendation["best_pick"]["public_rank"] == 1
    assert recommendation["best_pick"]["match_id"] == "f1"
    assert len(recommendation["alternatives"]) == 1
    assert recommendation["alternatives"][0]["public_rank"] == 2


def test_supported_and_lean_recommendations_exist_without_becoming_premium():
    supported = _pick(confidence=.62, fixture=_fixture("supported"))
    lean = _pick(confidence=.57, fixture=_fixture("lean"))
    result = build_recommendation_board(
        [supported, lean], [supported["_fixture"], lean["_fixture"]],
        date="2026-09-10",
    )
    classes = {
        item["match_id"]: item["classification"]
        for item in result["recommendations"]
    }
    assert classes == {"supported": "SUPPORTED", "lean": "LEAN"}
    assert not any(item["premium_eligible"] for item in result["recommendations"])


def test_subfloor_fixture_opinion_is_visible_as_lean_not_premium():
    pick = _pick("home_or_draw", confidence=.61)
    pick["market_floor_eligible"] = False
    pick["market_publication_floor"] = .65
    result = build_recommendation_board(
        [pick], [pick["_fixture"]], date="2026-09-10"
    )
    recommendation = result["recommendations"][0]
    assert recommendation["classification"] == "LEAN"
    assert recommendation["premium_eligible"] is False


def test_no_prediction_requires_an_explicit_reason():
    fixture = _fixture("empty")
    result = build_recommendation_board([], [fixture], date="2026-09-10")
    assert result["summary"]["no_prediction"] == 1
    assert result["no_prediction"][0]["reason"] == (
        "NO_CANDIDATE_CLEARED_BASE_DATA_AND_SANITY_GATES"
    )


def test_strong_requires_trusted_market_and_existing_premium_floor():
    trusted = _pick(confidence=.70)
    assert recommendation_classification({
        **trusted, "market_trust_state": "TRUSTED"
    }) == "STRONG"
    assert recommendation_classification({
        **trusted, "market_trust_state": "DEVELOPING"
    }) == "SUPPORTED"


def test_board_groups_by_wat_calendar_date():
    # 23:30 UTC belongs to the following day in Nigeria.
    fixture = _fixture(kickoff="2026-09-09T23:30:00Z")
    result = build_recommendation_board(
        [_pick(fixture=fixture)], [fixture], date="2026-09-10"
    )
    assert result["summary"]["fixtures_analysed"] == 1
