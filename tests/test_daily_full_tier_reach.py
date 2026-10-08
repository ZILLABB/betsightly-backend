"""BetSightly daily tier reach and Builder coverage contracts.

Official 10 Odds means at least 10.00x within at most 20 distinct matches.
Do not exchange model validity or SportyBet bookability for full cards.
"""
from datetime import datetime, timedelta, timezone
from math import prod

import pytest

from leagues import builder_v2, daily_feed
from leagues.publication_policy import enforce_card_policy, evaluate_slip
from tests.test_daily_portfolio import _pick as official_pick
from tests.test_builder_v2 import _pick as builder_pick, _wire as wire_builder


def _valid_leg(i, odds=1.45):
    leg = official_pick(i, "2099-01-01T18:00:00Z")
    leg.update(
        odds=odds,
        # Price and trust are validated independently; avoid having unrelated
        # model shrinkage obscure the integer target test.
        risk_adjusted_return=1.025,
        market_trust_state="TRUSTED",
    )
    return leg


def test_ten_odds_does_not_publish_a_9x_ticket_or_more_than_twenty_legs():
    six = [_valid_leg(i) for i in range(6)]
    assert prod(g["odds"] for g in six) < 10
    decision = evaluate_slip(six, "10_odds")
    assert not decision["allowed"]
    assert "TEN_ODDS_TARGET_NOT_REACHED" in decision["reasons"]

    seven = [_valid_leg(i) for i in range(7)]
    assert prod(g["odds"] for g in seven) >= 10
    assert evaluate_slip(seven, "10_odds")["allowed"]

    twenty_one = [_valid_leg(i) for i in range(21)]
    blocked = evaluate_slip(twenty_one, "10_odds")
    assert not blocked["allowed"]
    assert "TEN_ODDS_LEG_LIMIT_EXCEEDED" in blocked["reasons"]


def test_10_odds_booking_replacement_below_target_is_withheld():
    card = {
        "10_odds": {
            "selected": True, "games": [_valid_leg(i) for i in range(6)],
            "total_odds": 10.3,  # Stale claim cannot override actual leg prices.
            "presentation": "accumulator",
        }
    }
    enforce_card_policy(card)
    assert card["10_odds"]["selected"] is False
    assert card["10_odds"]["games"] == []
    assert "10.00x" in card["10_odds"]["reason"]


def test_official_selection_attempts_twenty_legs_for_five_and_ten(monkeypatch):
    from leagues import selection

    target = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    kickoff = f"{target}T18:00:00Z"
    picks = [official_pick(i, kickoff) for i in range(48)]
    calls = []

    def trace(pool, target, max_picks, min_confidence, min_ev,
              prefer="joint", band_low=.80, canonicalize=True):
        calls.append((target, max_picks, band_low, canonicalize))
        return ([], 0.0, 0.0), "Test portfolio search caps only"

    monkeypatch.setattr(daily_feed, "_select_tier", trace)
    monkeypatch.setattr(selection, "select_banker", lambda *args, **kwargs: ([], 0, 0))
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *args, **kwargs: {
        "selected": False, "games": [], "chain": [], "chain_length": 0,
    })
    result = daily_feed.build_daily_accumulators(preview={
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_wat_date": target,
        "picks": picks,
        "fixtures": [p["_fixture"] for p in picks],
    })
    assert result["locked"] is False
    assert len([c for c in calls if c[0] == 5.0]) == 2
    assert len([c for c in calls if c[0] == 10.0]) == 2
    assert all(cap == 20 for t, cap, lo, _ in calls if t in {5.0, 10.0})
    assert all(lo == 1.0 for t, cap, lo, _ in calls if t == 10.0)
    assert result["accumulators"]["10_odds"]["booking_rule"]["max_picks"] == 20
    assert result["accumulators"]["10_odds"]["booking_rule"]["band_low"] == 1.0


@pytest.mark.parametrize("mode,options", [
    ("target_odds", {"target_odds": 2.0}),
    ("strongest", {"max_games": 1}),
    ("game_count", {"game_count": 2}),
])
def test_builder_target_and_strongest_receive_all_approved_alternatives(
    monkeypatch, mode, options,
):
    from leagues import slip_builder

    wire_builder(monkeypatch, [builder_pick(0, odds=1.50),
                              builder_pick(1, odds=1.50)])
    calls = []

    def approved(pool, *, require_bookable=True, include_all_eligible=False):
        calls.append((require_bookable, include_all_eligible))
        return list(pool), {}

    monkeypatch.setattr(slip_builder, "approved_builder_candidates", approved)
    result = builder_v2.generate_v2({
        "mode": mode, "horizon": "7_days", **options,
    })
    assert calls and calls[0] == (True, True)
    assert result["mode"] == mode
