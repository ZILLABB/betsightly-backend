"""All six daily products reserve a fixture at most once."""
from leagues import daily_feed


def _card(**tiers):
    card = {
        key: {"selected": False, "games": []}
        for key in daily_feed.ALL_DAILY_PRODUCT_NAMES
    }
    card.update(tiers)
    return card


def _games(*ids):
    return [{"match_id": match_id} for match_id in ids]


def test_all_six_product_uniqueness_detects_over_1_5_against_accumulators():
    card = _card(
        banker={"selected": True, "games": _games("one")},
        **{
            "2_odds": {"selected": True, "games": _games("two")},
            "5_odds": {"selected": True, "games": _games("three")},
            "over_1_5": {"selected": True, "games": _games("one", "four")},
        },
    )
    assert daily_feed.all_daily_fixture_conflicts(card) == [
        {"match_id": "one", "products": ["banker", "over_1_5"]}
    ]
    card["over_1_5"]["games"] = _games("four")
    assert daily_feed.all_daily_fixture_conflicts(card) == []


def test_all_six_product_uniqueness_detects_repeat_inside_singles():
    card = _card(over_1_5={"selected": True, "games": _games("x", "x")})
    assert daily_feed.all_daily_fixture_conflicts(card) == [
        {"match_id": "x", "products": ["over_1_5", "over_1_5"]}
    ]

