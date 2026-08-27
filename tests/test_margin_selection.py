"""
Margin-aware selection.

The bookmaker's cut is not uniform across fixtures, and where two picks are
equally good the cheaper market is worth more. This checks that the preference
exists, and — more importantly — that it stays subordinate to confidence. A
cheap market must never buy its way past a genuinely stronger pick, because
the margin saved is measured in fractions of a point and the confidence given
up would not be.
"""

import pytest

from leagues.picks import ESTIMATE_MARGIN
from leagues.selection import (_mean_margin, select_accumulator, select_banker,
                               select_rollover_day)


def _pick(match_id, confidence, odds, margin=None, group="goals_over",
          market="over_1_5"):
    return {
        "match_id": match_id, "market": market, "market_group": group,
        "prediction": f"{market} on {match_id}",
        "confidence": confidence, "odds": odds,
        "odds_are_real": margin is not None,
        "odds_provider": "SportyBet" if margin is not None else None,
        "market_margin": margin,
        "expected_value": round(confidence * odds - 1.0, 4),
    }


# ── The margin figure itself ───────────────────────────────

def test_mean_margin_averages_real_margins():
    combo = [_pick("a", 0.8, 1.2, 0.04), _pick("b", 0.8, 1.2, 0.06)]
    assert _mean_margin(combo) == pytest.approx(0.05)


def test_estimated_prices_fall_back_to_the_assumed_margin():
    """An estimated price is our own probability plus a flat margin.

    It has to sort where its real equivalent would. Treating it as unknown and
    pushing it to the back would quietly bias the card towards whichever
    fixtures a bookmaker happened to price.
    """
    assert _mean_margin([_pick("a", 0.8, 1.2, None)]) == pytest.approx(
        ESTIMATE_MARGIN - 1.0)


def test_mean_margin_of_nothing_is_not_an_error():
    assert _mean_margin([]) == 0.0


# ── Ordering ───────────────────────────────────────────────

def test_cheaper_market_wins_between_equivalent_picks():
    """Same confidence, same price, different cut — take the cheaper cut."""
    picks = [
        _pick("dear", 0.80, 1.30, 0.070, market="over_1_5"),
        _pick("cheap", 0.80, 1.30, 0.035, market="over_1_5"),
    ]
    chosen, _, _ = select_banker(picks, min_confidence=0.70)
    assert chosen and chosen[0]["match_id"] == "cheap"


def test_confidence_still_outranks_margin():
    """The guard that keeps this honest.

    A much better pick at a dear price must beat a mediocre pick at a cheap
    one. Margin only decides inside a confidence band.
    """
    picks = [
        _pick("strong", 0.88, 1.20, 0.075),
        _pick("cheap_weak", 0.72, 1.30, 0.020),
    ]
    chosen, _, _ = select_banker(picks, min_confidence=0.70)
    assert chosen and chosen[0]["match_id"] == "strong"


def test_accumulator_prefers_the_cheaper_of_two_equal_slips():
    cheap = [_pick(f"c{i}", 0.72, 1.40, 0.030, market="over_1_5") for i in range(2)]
    dear = [_pick(f"d{i}", 0.72, 1.40, 0.075, market="over_2_5",
                  group="goals_over") for i in range(2)]
    chosen, combined, _ = select_accumulator(
        cheap + dear, target_odds=1.96, max_picks=2, min_confidence=0.70,
        band_low=0.90)
    assert chosen, "expected a slip at this target"
    assert combined == pytest.approx(1.96, abs=0.01)
    assert all(p["match_id"].startswith("c") for p in chosen), \
        [p["match_id"] for p in chosen]


def test_selection_works_when_no_pick_carries_a_margin():
    """A board with no bookmaker coverage must still produce a card."""
    picks = [_pick(f"p{i}", 0.72, 1.40, None) for i in range(4)]
    chosen, combined, joint = select_accumulator(
        picks, target_odds=1.96, max_picks=2, min_confidence=0.70,
        band_low=0.90)
    assert chosen and combined > 1.0 and 0.0 < joint <= 1.0


def test_mixed_real_and_estimated_prices_do_not_crash_the_search():
    picks = [
        _pick("a", 0.72, 1.40, 0.04),
        _pick("b", 0.72, 1.40, None),
        _pick("c", 0.70, 1.45, 0.06),
    ]
    chosen, combined, _ = select_accumulator(
        picks, target_odds=1.96, max_picks=2, min_confidence=0.70,
        band_low=0.90)
    assert chosen and combined > 1.0


# ── Expected-value ceiling ─────────────────────────────────

def test_a_slip_whose_typical_leg_beats_the_market_too_far_is_refused():
    """The search maximises expected value, so it reaches for the tail."""
    picks = [_pick(f"p{i}", 0.90, 1.40, 0.04) for i in range(4)]  # 1.26 per leg
    chosen, _, _ = select_accumulator(
        picks, target_odds=1.96, max_picks=2, min_confidence=0.70,
        band_low=0.90, max_leg_ev=1.04)
    assert not chosen, "a leg claiming a 26% edge should not be published"


def test_the_ceiling_leaves_ordinary_slips_alone():
    picks = [_pick(f"p{i}", 0.72, 1.40, 0.04) for i in range(4)]  # 1.008 per leg
    chosen, combined, _ = select_accumulator(
        picks, target_odds=1.96, max_picks=2, min_confidence=0.70,
        band_low=0.90, max_leg_ev=1.04)
    assert chosen and combined > 1.0


def test_the_ceiling_is_per_leg_so_long_slips_are_not_punished():
    """The bug this replaced: a flat slip-level cap emptied the 10 odds tier.

    Expected value compounds, so eight legs each a credible 3% above the
    market make 1.27 together. A flat cap at 1.10 refused every one of them
    on the richest day of the week, while waving through a two-leg slip at
    exactly the same per-leg optimism.
    """
    # Spread across market groups, or _PER_BAND_GROUP trims the candidate
    # list to four and the target becomes unreachable for reasons that have
    # nothing to do with the ceiling under test.
    groups = ["goals_over", "goals_under", "match_result",
              "team_goals_home", "team_goals_away", "dnb"]
    legs = [_pick(f"p{i}", 0.74, 1.40, 0.04, group=groups[i % len(groups)])
            for i in range(8)]  # 1.036 per leg
    chosen, combined, joint = select_accumulator(
        legs, target_odds=7.5, max_picks=8, min_confidence=0.70,
        band_low=0.80, max_leg_ev=1.04)
    assert chosen, "a long slip of individually credible legs must survive"
    assert (combined * joint) > 1.10,         "and its compounded value legitimately exceeds the old flat cap"


def test_floor_and_ceiling_can_both_bind():
    picks = [_pick(f"p{i}", 0.75, 1.40, 0.04) for i in range(4)]
    none, _, _ = select_accumulator(
        picks, target_odds=1.96, max_picks=2, min_confidence=0.70,
        band_low=0.90, min_ev=1.20, max_leg_ev=1.04)
    assert not none, "an impossible window should return nothing, not crash"


def test_rollover_can_use_up_to_six_short_safe_legs_inside_2x_to_3x():
    groups = ["goals_over", "goals_under", "match_result"]
    picks = [
        _pick(f"r{i}", 0.90, 1.13, 0.02, group=groups[i % len(groups)])
        for i in range(7)
    ]
    chosen, combined, joint = select_rollover_day(picks)
    assert len(chosen) == 6
    assert 2.0 <= combined <= 3.0
    assert joint == pytest.approx(0.9 ** 6, abs=0.001)
