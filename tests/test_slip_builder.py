from datetime import datetime, timedelta, timezone

import pytest

from leagues.api import _cached_slip_is_placeable
from leagues.daily_feed import _trusted_rollover_picks
from leagues.selection import select_accumulator
from leagues.slip_builder import _horizon_end, build_slip


def _pick(match_id="m1", odds=2.0, confidence=0.60, trusted=True,
          market_group="goals"):
    return {
        "match_id": match_id,
        "market_group": market_group,
        "odds": odds,
        "confidence": confidence,
        "bookable": True,
        "safe_tier_eligible": trusted,
    }


def test_today_horizon_ends_today_in_wat_not_tomorrow():
    now = datetime(2026, 8, 26, 22, 30, tzinfo=timezone.utc)  # 23:30 WAT
    end = _horizon_end(now, "today")
    assert end.date().isoformat() == "2026-08-26"
    assert end.hour == 22 and end.minute == 59


def test_week_horizon_contains_exactly_seven_wat_dates():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    end = _horizon_end(now, "week")
    assert end.date().isoformat() == "2026-09-01"
    assert end.hour == 22 and end.minute == 59


def test_expected_return_matches_this_slips_probability_and_odds():
    built = build_slip(2.0, pool=[_pick()], market_cap=10)
    assert built["ok"]
    assert built["hit_probability"] == pytest.approx(0.60)
    assert built["odds"] == pytest.approx(2.0)
    assert built["expected_return"] == pytest.approx(1.20)


def test_slip_builder_requires_exact_sportybet_bookability():
    pick = _pick()
    pick["bookable"] = False
    built = build_slip(2.0, pool=[pick], market_cap=10)
    assert not built["ok"]
    assert "SportyBet-bookable" in built["reason"]


def test_builder_caps_home_and_away_team_goal_picks_together():
    team_goals = [
        _pick(f"team-{i}", odds=1.5, confidence=0.80,
              market_group=("team_goals_home" if i % 2 == 0
                            else "team_goals_away"))
        for i in range(6)
    ]
    alternatives = [
        _pick(f"other-{i}", odds=1.5, confidence=0.78,
              market_group=f"other_{i}")
        for i in range(4)
    ]
    built = build_slip(10.0, pool=team_goals + alternatives,
                       max_legs=8, market_cap=3)
    assert built["ok"]
    selected_team_goals = [
        pick for pick in built["picks"]
        if pick["market_group"] in {"team_goals_home", "team_goals_away"}
    ]
    assert len(selected_team_goals) <= 3
    assert len({pick["market_group"] for pick in built["picks"]}) >= 3


def test_tier_selector_cannot_bypass_team_goal_cap_by_switching_sides():
    team_goals = [
        _pick(f"team-{i}", odds=1.5, confidence=0.80,
              market_group=("team_goals_home" if i % 2 == 0
                            else "team_goals_away"))
        for i in range(6)
    ]
    selected, _, _ = select_accumulator(
        team_goals, target_odds=5.0, max_picks=6,
        min_confidence=0.5, min_ev=0.0,
    )
    assert selected == []


def test_rollover_rejects_markets_without_their_own_evidence():
    trusted = _pick("trusted", trusted=True)
    new_market = _pick("new", trusted=False)
    assert _trusted_rollover_picks([new_market, trusted]) == [trusted]


def test_cached_slip_expires_before_booking_buffer():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    too_late = {"games": [{"kickoff": (now + timedelta(minutes=10)).isoformat()}]}
    placeable = {"games": [{"kickoff": (now + timedelta(minutes=30)).isoformat()}]}
    assert not _cached_slip_is_placeable(too_late, now)
    assert _cached_slip_is_placeable(placeable, now)


def test_cache_rejects_missing_or_invalid_kickoffs():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    assert not _cached_slip_is_placeable({"games": []}, now)
    assert not _cached_slip_is_placeable({"games": [{"kickoff": "bad"}]}, now)
