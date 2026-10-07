import inspect

from leagues import daily_feed
from leagues.publication_policy import enforce_card_policy


def test_official_rollover_is_gated_before_exposure_accounting():
    source = inspect.getsource(daily_feed.build_daily_accumulators)
    gate = source.index('_rollover_preallocation_card = {"rollover": rollover}')
    exposure = source.index("fixture_uses = {", gate)
    assert gate < exposure


def test_available_now_rollover_is_gated_before_exposure_accounting():
    source = inspect.getsource(daily_feed.build_bookable_now)
    gate = source.index('_live_rollover_preallocation_card = {"rollover": rollover}')
    exposure = source.index("fixture_uses = {", gate)
    assert gate < exposure


def test_blocked_rollover_releases_all_games():
    pick = {
        "match_id": "oct7-rollover-blocked",
        "market": "over_1_5",
        "prediction": "Over 1.5 Goals",
        "selection_probability": 0.74,
        "risk_adjusted_return": 1.04,
        "market_floor_eligible": True,
        "safe_tier_eligible": False,
        "market_trust_state": "TRUSTED",
        "bookable": True,
        "odds_are_real": True,
        "odds": 1.4,
        "league_slug": "bra.2",
        "competition_type": "LEAGUE",
    }
    card = {
        "rollover": {
            "selected": True,
            "games": [pick],
            "total_odds": 1.4,
            "hit_probability": 0.74,
            "presentation": "accumulator",
        }
    }

    enforce_card_policy(card)

    assert card["rollover"]["selected"] is False
    assert card["rollover"]["games"] == []
    assert card["rollover"]["result_status"] == "PUBLICATION_POLICY_BLOCKED"
    assert "INSUFFICIENT_SETTLED_EVIDENCE" in card["rollover"]["publication_policy"]["reasons"]


def test_locked_card_reader_is_not_patched_as_an_allocator():
    source = inspect.getsource(daily_feed.build_daily_accumulators)
    # There is one nested locked-card refresh _build_rollover call plus the
    # main direct publication call. Only the publication path gets the gate.
    assert source.count("_rollover_preallocation_card") == 3
