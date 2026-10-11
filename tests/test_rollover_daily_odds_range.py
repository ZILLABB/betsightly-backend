"""Regression coverage for strict 2.00x–4.00x rollover contract."""
import math

import pytest

from leagues import selection, publication_policy, booking
from leagues.rollover_odds_policy import rollover_odds_in_range


def _pick(index, odds=1.5, p=.69):
    return {
        "match_id": f"match-{index}",
        "market": "over_1_5", "market_group": "goals",
        "prediction": "Over 1.5 Goals",
        "odds": odds, "confidence": p,
        "selection_probability": p,
        "risk_adjusted_return": odds * p,
        "bookable": True, "odds_are_real": True,
        "safe_tier_eligible": True,
        "market_floor_eligible": True,
        "market_trust_state": "TRUSTED",
        "market_margin": .03,
        "trust": {
            "evidence_state": "SUPPORTED",
            "evidence_strength": 1.0,
            "evidence_adjusted_probability": p,
            "trust_grade": "A",
        },
    }


@pytest.mark.parametrize("odds,allowed", [
    (1.999, False), (2.0, True), (2.6, True),
    (3.99, True), (4.0, True), (4.001, False),
    (None, False), ("not-odds", False), (math.inf, False),
])
def test_rollover_price_contract(odds, allowed):
    assert rollover_odds_in_range(odds) is allowed


def test_rollover_picks_highest_joint_ticket_within_range():
    games = [_pick(i) for i in range(4)]
    selected, odds, joint = selection.select_rollover_day(games)
    assert len(selected) == 2
    assert odds == 2.25
    assert joint == pytest.approx(.4761)


def test_rollover_allows_three_or_four_x_when_target_is_higher():
    games = [_pick(i) for i in range(4)]
    selected, odds, joint = selection.select_rollover_day(games, target_odds=3)
    assert len(selected) == 3
    assert odds == pytest.approx(3.38)
    assert 3.0 <= math.prod(p["odds"] for p in selected) <= 4.0


@pytest.mark.parametrize("overshoot", [1.999, 4.001, 4.2])
def test_rollover_refuses_selector_fallback_outside_range(monkeypatch, overshoot):
    def forced(*args, **kwargs):
        return [_pick(1, odds=overshoot, p=.95)], overshoot, .95
    monkeypatch.setattr(selection, "select_accumulator", forced)
    assert selection.select_rollover_day([_pick(1)])[0] == []


@pytest.mark.parametrize("target", [1.3, 1.5, 4.1])
def test_rollover_rejects_out_of_band_target(target):
    assert selection.select_rollover_day([_pick(1)], target_odds=target)[0] == []


def test_publication_contract_rejects_any_out_of_band_rollover():
    for odds, allowed in [(1.82, False), (2.25, True), (4.001, False)]:
        legs = [_pick(1, odds=odds, p=.90)]
        result = publication_policy.evaluate_slip(legs, "rollover")
        assert result["allowed"] is allowed
        if not allowed:
            assert "ROLLOVER_ODDS_OUT_OF_RANGE" in result["reasons"]


def test_booking_attacher_hides_legacy_1_82x_code(monkeypatch):
    old = {
        "status": "active", "booking_status": "FULL",
        "share_code": "OLD182", "actual_sportybet_odds": 1.82,
    }
    monkeypatch.setattr(booking, "bookings_for", lambda day: {"rollover": old})
    published = {"rollover": {"selected": True,
                              "games": [_pick(1), _pick(2)]}}
    result = booking.attach_bookings("2026-10-11", published)
    assert "booking" not in result["rollover"]


def test_booking_attacher_keeps_valid_3x_code(monkeypatch):
    valid = {
        "status": "active", "booking_status": "FULL",
        "share_code": "VALID3", "actual_sportybet_odds": 3.01,
    }
    monkeypatch.setattr(booking, "bookings_for", lambda day: {"rollover": valid})
    monkeypatch.setattr(booking, "booking_lifecycle",
                        lambda record, games, now=None, **kw: record)
    published = {"rollover": {"selected": True,
                              "games": [_pick(1), _pick(2)]}}
    result = booking.attach_bookings("2026-10-11", published)
    assert result["rollover"]["booking"]["share_code"] == "VALID3"


@pytest.mark.parametrize("tier,old_price,new_price,rebooked_price", [
    ("rollover", 2.24, 1.822, 2.31),
    ("10_odds", 10.24, 9.82, 10.31),
])
def test_held_code_repriced_below_tier_must_be_rebooked(
    monkeypatch, tier, old_price, new_price, rebooked_price
):
    """Never mark a held code fresh after an out-of-policy readback."""
    from leagues import sportybet
    games = [
        {"match_id": f"match-{i}", "market": "over_1_5",
         "home_team": f"Home {i}", "away_team": f"Away {i}",
         "kickoff": "2099-01-01T18:00:00Z"}
        for i in (1, 2)
    ]
    prior = {
        "status": "active", "booking_status": "FULL",
        "share_code": "OLD_CODE",
        "actual_sportybet_odds": old_price,
        "final_booked_legs": games,
    }
    saved = []
    monkeypatch.setattr(booking, "bookings_for", lambda _: {tier: prior})
    monkeypatch.setattr(sportybet, "fetch_board", lambda **_: {"ok": True})
    monkeypatch.setattr(
        booking, "booking_lifecycle",
        lambda record, games, **kwargs: {"actionable": True},
    )
    monkeypatch.setattr(booking, "_booking_recheck_due", lambda _: True)
    monkeypatch.setattr(booking, "_revalidate_games", lambda games, board: (games, []))
    monkeypatch.setattr(
        booking, "selections_for",
        lambda games, board: ([{"eventId": g["match_id"]} for g in games], []),
    )
    monkeypatch.setattr(
        booking, "validate_code_details",
        lambda code, selections: (True, "ok", new_price),
    )
    monkeypatch.setattr(
        booking, "create_booking",
        lambda *args, **kwargs: {
            "status": "active", "booking_status": "FULL",
            "share_code": "REBOOKED", "actual_sportybet_odds": rebooked_price,
            "final_booked_legs": games,
        },
    )
    monkeypatch.setattr(booking, "_store", lambda day, t, record: saved.append(record))
    monkeypatch.setattr(booking, "_audit", lambda *args, **kwargs: None)

    report = booking.book_card("2099-01-01", {
        tier: {"selected": True, "games": games, "total_odds": old_price}
    })
    assert not report["skipped"]
    assert len(report["booked"]) == 1
    assert [r["share_code"] for r in saved] == ["REBOOKED"]


@pytest.mark.parametrize("tier,price", [
    ("rollover", 1.822), ("rollover", 4.01),
    ("10_odds", 9.99), ("rollover", float("nan")),
    ("10_odds", float("inf")), ("rollover", None),
])
def test_recheck_price_gate_is_fail_closed(tier, price):
    assert not booking._rechecked_tier_price_qualified(tier, price)
