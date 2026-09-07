from datetime import datetime, timedelta, timezone

import pytest

from leagues import slip_builder
from leagues.api import _cached_slip_is_placeable
from leagues.daily_feed import _trusted_rollover_picks
from leagues.selection import select_accumulator
from leagues.slip_builder import _horizon_end, build_slip


def _pick(match_id="m1", odds=2.0, confidence=0.60, trusted=True,
          market_group="goals", market="over_1_5"):
    return {
        "match_id": match_id,
        "market": market,
        "market_group": market_group,
        "odds": odds,
        "confidence": confidence,
        "bookable": True,
        "odds_are_real": True,
        "market_implied_probability": min(confidence, 1 / odds),
        "expected_value": min(.10, confidence * odds - 1),
        "safe_tier_eligible": trusted,
        "calibration_sample": 25 if trusted else 0,
        "sportybet_availability": {
            "status": "BOOKABLE",
            "sportybet_available": True,
            "board_snapshot_id": "test",
        },
        "_fixture": {"commence_time": "2099-01-01T12:00:00Z"},
        "_model": {"expected_goals": {"home": 1.5, "away": 1.5, "total": 3.0}},
    }


def _accept_trust(pick):
    return {
        "accepted": True, "evidence_adjusted_probability": pick["confidence"],
        "lower_reliability_bound": pick["confidence"] - .04,
        "evidence_strength": .9, "evidence_state": "SUPPORTED",
        "trust_score": 90, "trust_grade": "A", "rejection_reasons": [],
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
    assert built["hit_probability"] == pytest.approx(
        built["picks"][0]["evidence_adjusted_probability"]
    )
    assert built["odds"] == pytest.approx(2.0)
    assert built["expected_return"] == pytest.approx(built["hit_probability"] * 2.0)


def test_slip_builder_requires_exact_sportybet_bookability():
    pick = _pick()
    pick["bookable"] = False
    built = build_slip(2.0, pool=[pick], market_cap=10)
    assert not built["ok"]
    assert "SportyBet-bookable" in built["reason"]


def test_builder_caps_actual_home_and_away_team_goal_picks_together(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    team_goals = [
        _pick(
            f"team-{i}",
            odds=2.0,
            confidence=0.80,
            market_group=("team_goals_home" if i % 2 == 0 else "team_goals_away"),
            market=("home_over_0_5" if i % 2 == 0 else "away_over_0_5"),
        )
        for i in range(10)
    ]
    alternatives = [
        _pick(f"other-{i}", odds=2.0, confidence=0.78, market_group="goals_over_1_5")
        for i in range(6)
    ]
    built = build_slip(10.0, pool=team_goals + alternatives, max_legs=10, market_cap=3)
    assert built["ok"]
    selected_team_goals = [
        pick
        for pick in built["picks"]
        if pick["market_group"] in {"team_goals_home", "team_goals_away"}
    ]
    assert len(selected_team_goals) <= 2


@pytest.mark.parametrize("target", [5, 10, 20, 50, 70, 100])
def test_actual_team_to_score_cap_holds_for_every_builder_target(monkeypatch, target):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    team_goals = [
        _pick(f"tts-{i}", odds=2.0, confidence=.82,
              market=("home_over_0_5" if i % 2 == 0 else "away_over_0_5"),
              market_group=("team_goals_home" if i % 2 == 0 else "team_goals_away"))
        for i in range(10)
    ]
    diverse = (
        [_pick(f"over-{i}", 2.0, .80, market_group="goals_over_1_5") for i in range(3)]
        + [_pick(f"under-{i}", 2.0, .80, market="under_4_5",
                 market_group="goals_under_4_5") for i in range(2)]
        + [_pick(f"dc-{i}", 2.0, .80, market="home_or_draw",
                 market_group="double_chance") for i in range(3)]
    )
    built = build_slip(target, pool=team_goals + diverse, max_legs=16, market_cap=3)
    assert built["ok"], built
    assert built["team_to_score_leg_count"] <= 2


def test_under_exposure_cap_uses_actual_under_markets(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    unders = [
        _pick(f"under-{i}", 2.0, .82,
              market=("under_3_5" if i % 2 else "under_4_5"),
              market_group=("goals_under_3_5" if i % 2 else "goals_under_4_5"))
        for i in range(10)
    ]
    overs = [_pick(f"over-u-{i}", 2.0, .80, market_group="goals_over_1_5")
             for i in range(3)]
    built = build_slip(20, pool=unders + overs, max_legs=10, market_cap=3)
    assert built["ok"], built
    assert built["under_leg_count"] <= 2


@pytest.mark.parametrize("target", [10, 70])
def test_high_quality_synthetic_board_can_reach_large_targets(monkeypatch, target):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    board = (
        [_pick(f"over-r-{i}", 2.0, .82, market_group="goals_over_1_5") for i in range(3)]
        + [_pick(f"under-r-{i}", 2.0, .82, market="under_4_5",
                 market_group="goals_under_4_5") for i in range(2)]
        + [_pick(f"dc-r-{i}", 2.0, .82, market="home_or_draw",
                 market_group="double_chance") for i in range(3)]
    )
    built = build_slip(target, pool=board, max_legs=16, market_cap=3)
    assert built["ok"], built
    assert built["result_status"] == "TARGET_REACHED"
    assert built["odds"] >= target


def test_builder_market_cap_never_relaxes_for_high_targets():
    assert slip_builder._market_cap_for_target(10) == 3
    assert slip_builder._market_cap_for_target(20) == 3
    assert slip_builder._market_cap_for_target(30) == 3
    assert slip_builder._market_cap_for_target(50) == 3
    assert slip_builder._market_cap_for_target(70) == 3
    assert slip_builder._market_cap_for_target(100) == 3

def test_builder_locally_replaces_a_weaker_selected_fixture(
    monkeypatch,
):
    # Keep this test focused on combination search rather than the separate
    # trust/evidence model. Use each pick's supplied confidence directly.
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)

    # Preserve the artificial ordering so the stronger replacement sits
    # outside the first 48 seeded alternatives.
    monkeypatch.setattr(
        slip_builder,
        "_best_per_fixture_group",
        lambda pool: list(pool),
    )

    blocker = _pick(
        "bad-fixture",
        odds=2.90,
        confidence=0.80,
        market_group="goals",
    )

    decoys = [
        _pick(
            "bad-fixture",
            odds=3.00,
            confidence=0.70,
            market_group="goals",
        )
        for _ in range(48)
    ]

    replacement = _pick(
        "better-fixture",
        odds=2.00,
        confidence=0.90,
        market_group="goals",
    )

    anchor = _pick(
        "anchor",
        odds=2.00,
        confidence=0.90,
        market_group="other",
    )

    built = build_slip(
        4.0,
        pool=[
            blocker,
            *decoys,
            replacement,
            anchor,
        ],
        max_legs=2,
        market_cap=1,
    )

    assert built["ok"]
    assert built["odds"] == pytest.approx(4.0)
    assert built["hit_probability"] == pytest.approx(
        0.81,
    )

    assert {
        pick["match_id"]
        for pick in built["picks"]
    } == {
        "better-fixture",
        "anchor",
    }

def test_high_target_builder_quality_caps_instead_of_using_four_of_one_group(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    picks = [
        _pick(
            f"high-target-{i}",
            odds=3.0,
            confidence=0.80,
            market_group="goals",
        )
        for i in range(4)
    ]

    built = build_slip(
        70.0,
        pool=picks,
        max_legs=4,
    )

    assert not built["ok"]
    assert built["result_status"] == "EXPOSURE_CAPPED"
    assert built["optimization_status"] == "OPTIMAL"


def test_builder_can_use_deeper_public_alternative_without_repeating_fixture(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    fixture_alternatives = [
        _pick("shared", 1.10, .90, market="over_1_5", market_group="goals"),
        _pick("shared", 1.12, .88, market="under_4_5", market_group="under"),
        _pick("shared", 2.00, .70, market="home_or_draw", market_group="double_chance"),
    ]
    anchor = _pick("anchor-deep", 2.00, .82, market_group="other")
    built = build_slip(4, pool=fixture_alternatives + [anchor], max_legs=2,
                       market_cap=3)
    assert built["ok"], built
    assert built["optimization_status"] == "OPTIMAL"
    assert len({pick["match_id"] for pick in built["picks"]}) == len(built["picks"])
    assert any(p["match_id"] == "shared" and p["public_rank"] >= 3
               for p in built["picks"])


def test_builder_restricted_alternative_never_enters_optimizer(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    restricted = _pick("restricted", 3.0, .90, market="under_2_5",
                       market_group="under")
    safe = _pick("safe", 2.0, .82)
    built = build_slip(3, pool=[restricted, safe], max_legs=2, market_cap=3)
    assert all(p["market"] != "under_2_5" for p in built.get("picks", []))
    assert built["after_policy"] == 1


def test_tier_selector_cannot_bypass_team_goal_cap_by_switching_sides():
    team_goals = [
        _pick(
            f"team-{i}",
            odds=1.5,
            confidence=0.80,
            market_group=("team_goals_home" if i % 2 == 0 else "team_goals_away"),
        )
        for i in range(6)
    ]
    selected, _, _ = select_accumulator(
        team_goals,
        target_odds=5.0,
        max_picks=6,
        min_confidence=0.5,
        min_ev=0.0,
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


def test_generate_reuses_availability_from_same_board_snapshot(monkeypatch):
    availability = {
        "status": "BOOKABLE",
        "sportybet_available": True,
        "sportybet_odds": 2.0,
        "board_snapshot_id": "snap-1",
    }
    pick = {
        **_pick(),
        "sportybet_availability": availability,
        "_fixture": {
            "home": {"name": "Home"},
            "away": {"name": "Away"},
            "commence_time": "2026-09-04T12:00:00Z",
            "league": "League",
        },
    }
    monkeypatch.setattr(slip_builder, "_pool", lambda *a, **k: [pick])
    monkeypatch.setattr(
        "leagues.sportybet.fetch_board",
        lambda **k: {"__meta__": {"snapshot_id": "snap-1"}},
    )
    monkeypatch.setattr(
        "leagues.sportybet.availability_for",
        lambda *a, **k: pytest.fail("same-snapshot pick must not be rematched"),
    )
    monkeypatch.setattr(
        slip_builder,
        "build_slip",
        lambda *a, **k: {
            "ok": True,
            "odds": 2.0,
            "legs": 1,
            "hit_probability": 0.6,
            "expected_return": 1.2,
            "avg_confidence": 0.6,
            "picks": [pick],
        },
    )
    monkeypatch.setattr(
        "leagues.picks.to_game", lambda p: {"kickoff": "2026-09-04T12:00:00Z"}
    )
    monkeypatch.setattr(
        "leagues.booking.create_or_reuse_generated_booking",
        lambda *a, **k: {
            "status": "active",
            "share_code": "ABC123",
            "timing_ms": {"validation_readback": 4},
        },
    )

    result = slip_builder.generate(2, horizon="week")

    assert result["status"] == "success"
    assert result["booking"]["share_code"] == "ABC123"
    assert result["timing_ms"]["fixture_matching"] >= 0
    assert result["timing_ms"]["validation_readback"] == 4


def test_builder_does_not_accept_odds_below_requested_target():
    picks = [
        _pick("target-1", odds=1.50, confidence=0.80),
        _pick("target-2", odds=1.50, confidence=0.80),
        _pick("target-3", odds=1.50, confidence=0.80),
    ]

    # 1.50 ^ 3 = 3.375, which is below the requested 3.50x.
    built = build_slip(
        3.50,
        pool=picks,
        max_legs=3,
        market_cap=10,
    )

    assert not built["ok"]
    assert built["best_reachable"] == pytest.approx(3.38)


def test_dnb_settlement_math_models_draw_as_push():
    pick = {
        "market": "dnb_home",
        "odds": 1.50,
        "confidence": 0.80,
        "evidence_adjusted_probability": 0.80,
        "_model": {
            "probabilities": {
                "home_win": 0.50,
                "draw": 0.25,
                "away_win": 0.25,
            }
        },
    }

    settlement = slip_builder._leg_settlement_probabilities(pick)

    assert settlement is not None

    win, push, loss = settlement

    assert win == pytest.approx(0.60)
    assert push == pytest.approx(0.25)
    assert loss == pytest.approx(0.15)


def test_dnb_push_reduces_payout_without_losing_accumulator():
    dnb = {
        "market": "dnb_home",
        "odds": 2.00,
        "confidence": 0.80,
        "evidence_adjusted_probability": 0.80,
        "_model": {
            "probabilities": {
                "home_win": 0.50,
                "draw": 0.25,
                "away_win": 0.25,
            }
        },
    }

    binary = {
        "market": "over_1_5",
        "odds": 2.00,
        "confidence": 0.70,
        "evidence_adjusted_probability": 0.70,
    }

    distribution = slip_builder._positive_payout_distribution([dnb, binary])

    assert distribution[4.0] == pytest.approx(0.42)
    assert distribution[2.0] == pytest.approx(0.175)
    assert sum(distribution.values()) == pytest.approx(0.595)


def test_builder_team_goal_cap_never_scales_with_target():
    for target in (10, 20, 30, 50, 70, 100):
        assert slip_builder._team_to_score_cap_for_target(target) == 2
