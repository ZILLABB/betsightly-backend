"""Synthetic domestic-cup inventory tests. No live odds or web requests."""
from leagues.cup_supply_diagnostics import domestic_cup_supply


def pick(mid="c1", league="esp.copa_del_rey", market="over_1_5",
         sample=5, price=True, booked=False):
    return {
        "match_id": mid, "market": market,
        "_fixture": {"league_slug": league,
                     "competition_type": "DOMESTIC_CUP",
                     "competition_historical_sample": sample},
        "odds_are_real": price, "bookable": booked,
        "sportybet_availability": {"status": (
            "BOOKABLE" if booked else "FIXTURE_NOT_FOUND")},
    }


def test_busy_cup_can_be_visible_without_eligible_official_picks():
    future = [pick(f"c{i}") for i in range(12)]
    daily = [pick(f"c{i}") for i in range(8)]
    rejected = [
        {"match_id": f"c{i}", "market": "over_1_5",
         "reasons": ["INSUFFICIENT_SETTLED_EVIDENCE", "NOT_EXACTLY_BOOKABLE"]}
        for i in range(8)
    ]
    result = domestic_cup_supply(future, daily, [], rejected)
    row = result["competitions"]["esp.copa_del_rey"]
    assert result["total_future_cup_fixtures"] == 12
    assert result["total_day_cup_fixtures"] == 8
    assert result["total_official_cup_legs"] == 0
    assert row["daily_competition_history_lt_20_fixtures"] == 8
    assert row["rejection_reasons"]["NOT_EXACTLY_BOOKABLE"] == 8
    assert row["bookmaker_unavailable_reasons"]["FIXTURE_NOT_FOUND"] == 8
    assert result["policy_changed"] is False


def test_qualified_cup_and_regular_league_are_never_confused():
    cup = pick(sample=30, booked=True)
    regular = pick(mid="l1", league="esp.1", sample=30, booked=True)
    out = domestic_cup_supply([cup, regular], [cup, regular],
                              [cup, regular], [])
    assert set(out["competitions"]) == {"esp.copa_del_rey"}
    row = out["competitions"]["esp.copa_del_rey"]
    assert row["daily_bookable_fixtures"] == 1
    assert row["daily_competition_history_ge_20_fixtures"] == 1
    assert row["official_allowed_selections"] == 1


def test_fixture_counts_dedupe_multiple_cup_markets():
    first = pick(market="home_win", booked=True)
    second = pick(market="over_1_5", booked=True)
    out = domestic_cup_supply([first, second], [first, second],
                              [first], [{"match_id": "c1",
                                        "market": "over_1_5",
                                        "reasons": ["NEGATIVE_MODEL_VALUE"]}])
    row = out["competitions"]["esp.copa_del_rey"]
    assert row["future_fixtures"] == 1
    assert row["daily_fixtures"] == 1
    assert row["daily_canonical_selections"] == 2
    assert row["official_allowed_selections"] == 1
    assert row["rejection_reasons"]["NEGATIVE_MODEL_VALUE"] == 1


def test_other_cups_keep_independent_rejection_reason_counts():
    italy = pick(mid="i1", league="ita.coppa_italia", booked=True)
    germany = pick(mid="g1", league="ger.dfb_pokal", booked=False)
    out = domestic_cup_supply(
        [italy, germany], [italy, germany], [italy],
        [{"match_id": "g1", "market": "over_1_5",
          "reasons": ["NOT_EXACTLY_BOOKABLE"]}],
    )
    assert out["competitions"]["ita.coppa_italia"]["official_allowed_selections"] == 1
    assert out["competitions"]["ger.dfb_pokal"]["official_allowed_selections"] == 0
    assert out["competitions"]["ger.dfb_pokal"]["rejection_reasons"] == {
        "NOT_EXACTLY_BOOKABLE": 1
    }


def test_rejection_cannot_be_attributed_to_other_match_or_market():
    copa = pick()
    out = domestic_cup_supply(
        [copa], [copa], [],
        [{"match_id": "c2", "market": "over_1_5",
          "reasons": ["INSUFFICIENT_SETTLED_EVIDENCE"]},
         {"match_id": "c1", "market": "away_win",
          "reasons": ["NEGATIVE_MODEL_VALUE"]}],
    )
    assert not out["competitions"]["esp.copa_del_rey"]["rejection_reasons"]


def test_no_cups_is_valid_and_does_not_invent_coverage():
    league = pick(league="eng.1")
    out = domestic_cup_supply([league], [league], [], [])
    assert out["total_future_cup_fixtures"] == 0
    assert out["competitions"] == {}
