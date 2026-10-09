"""Regression: official 10x can search real 19/20-leg combinations safely."""
import math

from leagues.selection import select_accumulator


def _p(i, *, odds=1.125, probability=.89, match_id=None):
    return {
        "match_id": match_id or f"fixture-{i}",
        "market": f"market-{i % 10}",
        "market_group": f"market-group-{i % 10}",
        "prediction": "Qualified outcome",
        "odds": odds,
        "confidence": probability,
        "selection_probability": probability,
        "odds_are_real": True,
        "bookable": True,
        "market_margin": .02,
        "expected_value": odds * probability - 1,
    }


def test_twenty_leg_ten_odds_no_longer_blocked_by_eighteen_candidate_cap():
    # Nineteen 1.125x legs return only 9.64x. A valid 10x exists with twenty
    # distinct qualified markets across ten group families.
    picks = [_p(i) for i in range(24)]
    selected, odds, joint = select_accumulator(
        picks, target_odds=10.0, max_picks=20,
        min_confidence=.65, min_ev=1.0,
        band_low=1.0, canonicalize=False,
    )
    assert len(selected) == 20
    assert 10.0 <= odds < 11
    assert len({p["match_id"] for p in selected}) == 20
    assert math.isclose(joint, .89 ** 20, rel_tol=1e-3)


def test_long_search_never_accepts_negative_return_to_fill():
    selected, odds, joint = select_accumulator(
        [_p(i, probability=.66) for i in range(24)],
        target_odds=10.0, max_picks=20,
        min_confidence=.65, min_ev=1.0,
        band_low=1.0, canonicalize=False,
    )
    assert selected == [] and odds == 0 and joint == 0


def test_long_search_enforces_market_group_and_fixture_caps():
    picks = [_p(i) for i in range(24)]
    # Extra market alternatives for the same match may be examined but
    # cannot appear twice in the final accumulator.
    for i in range(5):
        alternate = _p(i + 100, match_id=f"fixture-{i}")
        picks.append(alternate)
    chosen, odds, _ = select_accumulator(
        picks, target_odds=10.0, max_picks=20,
        min_confidence=.65, min_ev=1.0,
        band_low=1.0, canonicalize=False,
    )
    assert 10 <= odds
    assert len(chosen) <= 20
    assert len({p["match_id"] for p in chosen}) == len(chosen)
    assert all(
        sum(p["market_group"] == g for p in chosen) <= 3
        for g in {p["market_group"] for p in chosen}
    )


def test_ten_odds_unreachable_with_19_legs_remains_empty():
    chosen, odds, _ = select_accumulator(
        [_p(i) for i in range(24)],
        target_odds=10.0, max_picks=19,
        min_confidence=.65, min_ev=1.0,
        band_low=1.0, canonicalize=False,
    )
    assert chosen == [] and odds == 0
