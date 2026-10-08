from leagues.publication_policy import (
    BANKER_MIN_PROBABILITY,
    POLICY_VERSION,
    enforce_card_policy,
    evaluate_leg,
    evaluate_slip,
    filter_official_candidates,
)


def pick(*, confidence=.75, odds=1.45, market="over_1_5",
         league_slug="eng.1", competition_type="LEAGUE",
         bookable=True, real=True, safe=True):
    return {
        "match_id": "m1",
        "market": market,
        "market_group": "goals",
        "prediction": market,
        "confidence": confidence,
        "odds": odds,
        "odds_are_real": real,
        "bookable": bookable,
        "safe_tier_eligible": safe,
        "market_floor_eligible": True,
        "market_trust_state": "TRUSTED",
        "trust": {
            "accepted": True,
            "trust_grade": "A",
            "evidence_adjusted_probability": confidence,
            "lower_reliability_bound": max(.01, confidence - .01),
            "evidence_strength": 1.0,
        },
        "_fixture": {
            "league_slug": league_slug,
            "competition_type": competition_type,
        },
        "_model": {"probabilities": {"draw": .25}},
    }


def test_positive_real_bookable_leg_passes_contract():
    decision = evaluate_leg(pick(), "2_odds")
    assert decision["allowed"] is True
    assert decision["policy_version"] == POLICY_VERSION
    assert decision["risk_adjusted_return"] >= 1.0


def test_october_five_negative_price_is_rejected_even_when_probability_is_high():
    # Córdoba shape from 2026-10-05: 75% at 1.30 looked safe but was
    # negative at the offered price. Conservative probability is stricter.
    decision = evaluate_leg(pick(confidence=.75, odds=1.30), "2_odds")
    assert decision["allowed"] is False
    assert "NEGATIVE_MODEL_VALUE" in decision["reasons"]


def test_friendlies_never_enter_official_products():
    decision = evaluate_leg(
        pick(league_slug="fifa.friendly", competition_type="INTERNATIONAL_FRIENDLY"),
        "5_odds",
    )
    assert decision["allowed"] is False
    assert "FRIENDLY_COMPETITION" in decision["reasons"]


def test_estimated_or_unbookable_prices_are_analysis_only():
    estimated = evaluate_leg(pick(real=False), "over_1_5")
    unbookable = evaluate_leg(pick(bookable=False), "over_1_5")
    assert "ESTIMATED_PRICE" in estimated["reasons"]
    assert "NOT_EXACTLY_BOOKABLE" in unbookable["reasons"]


def test_banker_never_falls_back_below_72_percent():
    p = pick(confidence=BANKER_MIN_PROBABILITY - .01, odds=1.50)
    decision = evaluate_leg(p, "banker")
    assert decision["allowed"] is False
    assert "BELOW_PRODUCT_PROBABILITY_FLOOR" in decision["reasons"]


def test_whole_slip_is_fail_closed():
    good = pick(confidence=.75, odds=1.45)
    good2 = {**pick(confidence=.74, odds=1.46), "match_id": "m2"}
    bad = {**pick(confidence=.75, odds=1.25), "match_id": "m3"}
    assert evaluate_slip([good, good2], "2_odds")["allowed"] is True
    blocked = evaluate_slip([good, bad], "2_odds")
    assert blocked["allowed"] is False
    assert "NEGATIVE_MODEL_VALUE" in blocked["reasons"]


def test_filter_reports_why_candidate_was_removed():
    allowed, rejected = filter_official_candidates(
        [pick(), {**pick(odds=1.20), "match_id": "bad"}], "5_odds"
    )
    assert len(allowed) == 1
    assert len(rejected) == 1
    assert "NEGATIVE_MODEL_VALUE" in rejected[0]["reasons"]


def test_final_card_guard_withholds_invalid_accumulator():
    game = pick(confidence=.75, odds=1.25)
    game.pop("_fixture")
    game.update(league_slug="eng.1", competition_type="LEAGUE")
    accumulators = {
        "2_odds": {
            "selected": True,
            "games": [game],
            "total_odds": 1.25,
            "hit_probability": .75,
            "presentation": "accumulator",
        }
    }
    report = enforce_card_policy(accumulators)
    assert accumulators["2_odds"]["selected"] is False
    assert accumulators["2_odds"]["result_status"] == "PUBLICATION_POLICY_BLOCKED"
    assert report["products"]["2_odds"]["allowed"] is False


def test_final_publication_contract_blocks_cross_product_fixture_overlap():
    """Even a code-time replacement cannot share an official match."""
    banker = pick(confidence=.78, odds=1.45)
    over = pick(confidence=.75, odds=1.45)
    card = {
        "banker": {
            "selected": True, "games": [banker],
            "presentation": "accumulator",
        },
        "over_1_5": {
            "selected": True, "games": [over],
            "presentation": "singles",
            "booking": {"actionable": True, "share_code": "STALE"},
        },
    }

    report = enforce_card_policy(card)
    assert report["products"]["banker"]["allowed"] is True
    assert report["products"]["over_1_5"]["allowed"] is False
    assert report["products"]["over_1_5"]["duplicate_fixture_ids"] == ["m1"]
    assert "DUPLICATE_FIXTURE_ACROSS_OFFICIAL_PRODUCTS" in (
        report["products"]["over_1_5"]["reasons"]
    )
    assert card["over_1_5"]["selected"] is False
    assert card["over_1_5"]["games"] == []
    assert "booking" not in card["over_1_5"]


def test_final_publication_contract_allows_unique_fixtures_across_products():
    card = {
        "banker": {
            "selected": True, "games": [pick(confidence=.78, odds=1.45)],
            "presentation": "accumulator",
        },
        "over_1_5": {
            "selected": True, "games": [
                {**pick(confidence=.75, odds=1.45), "match_id": "m2"}
            ],
            "presentation": "singles",
        },
    }
    report = enforce_card_policy(card)
    assert report["products"]["banker"]["allowed"] is True
    assert report["products"]["over_1_5"]["allowed"] is True
    assert card["over_1_5"]["selected"] is True
