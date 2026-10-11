"""10 Odds must reach real 10x without weakening leg quality or market trust."""
import pytest
from leagues import daily_feed, booking
from leagues.selection import select_accumulator
from leagues.publication_policy import evaluate_slip


def _goal(mid, odds=1.40):
    return {
        "match_id": str(mid), "home_team": "Home " + str(mid),
        "away_team": "Away " + str(mid), "market": "over_1_5",
        "market_group": "goals", "prediction": "Over 1.5 Goals",
        "odds": odds, "confidence": .725, "selection_probability": .725,
        "bookable": True, "odds_are_real": True,
        "safe_tier_eligible": True, "market_floor_eligible": True,
        "market_trust_state": "TRUSTED",
        "risk_adjusted_return": round(odds * .725, 6),
        "market_margin": .04,
        "kickoff": "2099-01-01T12:00:00Z",
        "commence_time": "2099-01-01T12:00:00Z",
    }


def test_seven_independent_goals_are_genuinely_selectable_at_10x():
    pool = [_goal(i) for i in range(7)]
    original = select_accumulator(
        pool, 10, 20, .65, min_ev=1.0, prefer="joint",
        band_low=1.0, canonicalize=False)
    assert original[0] == []
    selection, odds, probability = select_accumulator(
        pool, 10, 20, .65, min_ev=1.0, prefer="joint",
        band_low=1.0, canonicalize=False, market_cap=7)
    assert len(selection) == 7
    assert len({p["match_id"] for p in selection}) == 7
    assert odds >= 10.0
    assert .08 < probability < .14
    verdict = evaluate_slip(selection, "10_odds")
    assert verdict["allowed"], verdict["reasons"]
    assert verdict["model_estimated_return"] >= 1.0


def test_daily_10x_uses_same_cap_only_when_explicitly_requested():
    pool = [_goal(i) for i in range(7)]
    safe, _ = daily_feed._select_tier(
        pool, 10.0, 20, .65, 1.0,
        band_low=1.0, canonicalize=False, market_cap=7)
    assert len(safe[0]) == 7
    withheld, _ = daily_feed._select_tier(
        pool, 10.0, 20, .65, 1.0,
        band_low=1.0, canonicalize=False)
    assert withheld[0] == []


def test_booking_replacement_respects_10x_market_cap():
    pool = [_goal(i) for i in range(7)]
    result = booking._select_bookable_variant(
        pool, {"selector": "accumulator", "target": 10.0,
               "max_picks": 20, "min_confidence": .65, "min_ev": 1.0,
               "band_low": 1.0, "market_cap": 7})
    assert len(result[0]) == 7
    assert result[1] >= 10.0
    default = booking._select_bookable_variant(
        pool, {"selector": "accumulator", "target": 10.0,
               "max_picks": 20, "min_confidence": .65, "min_ev": 1.0,
               "band_low": 1.0})
    assert not default[0]


def test_duplicate_fixture_cannot_buy_target_even_at_higher_cap():
    pool = [_goal(i) for i in range(6)] + [_goal(0)]
    selected, odds, _ = select_accumulator(
        pool, 10, 20, .65, min_ev=1.0,
        band_low=1.0, canonicalize=False, market_cap=7)
    assert selected == []
    assert odds == 0


def test_low_value_seven_goal_ticket_still_fails():
    pool = [_goal(i) for i in range(7)]
    for pick in pool:
        pick["selection_probability"] = .69
        pick["confidence"] = .69
        pick["risk_adjusted_return"] = .966
    result = select_accumulator(pool, 10, 20, .65, min_ev=1.0,
        band_low=1.0, canonicalize=False, market_cap=7)
    assert result[0] == []


def test_stale_but_six_hour_safe_prepared_board_does_not_block_recovery(
        monkeypatch):
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _date: {
        "10_odds": {"selected": False, "games": []}})
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: "2099-01-01")
    monkeypatch.setattr("leagues.engine.prepared_board_status", lambda **_:
                        {"ready": True, "stale": True, "age_seconds": 4000})
    monkeypatch.setattr("leagues.engine.prepared_pipeline",
                        lambda **_: ([], []))
    monkeypatch.setattr("leagues.engine.run_pipeline",
                        lambda **_: (_ for _ in ()).throw(
                            AssertionError("recovery must not refetch pipeline")))
    result = daily_feed.recover_today_empty_tiers()
    assert result["status"] == "COMPLETE"
    assert result["tiers"]["10_odds"]["status"] == "UNREACHABLE"


def test_board_outside_valid_stale_window_remains_blocked(monkeypatch):
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _date: {
        "10_odds": {"selected": False, "games": []}})
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: "2099-01-01")
    monkeypatch.setattr("leagues.engine.prepared_board_status", lambda **_:
                        {"ready": False, "stale": True, "age_seconds": 24000})
    monkeypatch.setattr("leagues.engine.prepared_pipeline",
                        lambda **_: (_ for _ in ()).throw(
                            AssertionError("expired board must not be used")))
    result = daily_feed.recover_today_empty_tiers()
    assert result["status"] == "BOARD_UNAVAILABLE"


@pytest.mark.parametrize("bad", [0, -1, 21, 2.5, True])
def test_invalid_market_cap_is_rejected(bad):
    with pytest.raises(ValueError):
        select_accumulator([_goal("x")], 10, canonicalize=False,
                           market_cap=bad)
