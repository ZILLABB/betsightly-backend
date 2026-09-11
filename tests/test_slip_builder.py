from datetime import datetime, timedelta, timezone

import pytest

from leagues import slip_builder
from leagues.api import _cached_slip_is_placeable
from leagues.daily_feed import _trusted_rollover_picks
from leagues.selection import select_accumulator
from leagues.slip_builder import (
    _aggregate_credibility,
    _constraint_counterfactuals,
    _horizon_end,
    build_slip,
)


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


def test_aggregate_credibility_challenges_edge_not_supported_by_lower_bounds():
    legs = [_pick("m1", odds=2.0, confidence=.80),
            _pick("m2", odds=2.0, confidence=.80)]
    for leg in legs:
        leg["evidence_adjusted_probability"] = .80
        leg["trust"] = {"lower_reliability_bound": .45}
        leg["_fixture"]["league"] = "Shared league"
    result = _aggregate_credibility(
        legs, odds=4.0, expected_return=2.56,
        model_hit_probability=.64,
    )
    assert result["status"] == "EDGE_NOT_SUPPORTED_BY_LOWER_BOUNDS"
    assert result["extraordinary_claim"] is True
    assert result["conservative_expected_return"] < 1
    assert result["action"] == "LOWER_BOUND_APPLIED_TO_SELECTION"


def test_aggregate_credibility_reports_missing_lower_bounds():
    leg = _pick("m1", odds=1.5, confidence=.75)
    leg["evidence_adjusted_probability"] = .75
    leg["trust"] = {}
    result = _aggregate_credibility(
        [leg], odds=1.5, expected_return=1.125,
        model_hit_probability=.75,
    )
    assert result["status"] == "INSUFFICIENT_LOWER_BOUND_EVIDENCE"
    assert result["missing_lower_bounds"] == 1


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
        built["picks"][0]["selection_probability"]
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


def test_counterfactual_primary_constraint_comes_from_effect_not_saturation(monkeypatch):
    calls = []

    def solve(candidates, target, max_legs, market_cap, team_cap,
              under_cap=None, enforce_team_diversity=True,
              required_selection_ids=None):
        calls.append((id(candidates), max_legs, market_cap, team_cap,
                      enforce_team_diversity))
        odds = 80.0
        if max_legs > 16:
            odds = 210.0
        return odds, .01, candidates[:1], "OPTIMAL"

    monkeypatch.setattr(slip_builder, "_verified_optimize", solve)
    pick = _pick(odds=2, confidence=.8)
    pick.update(selection_probability=.8, risk_adjusted_return=1.6,
                trust={"trust_grade": "A"})
    result = _constraint_counterfactuals([pick], 200, 16, 6, 2, 2)
    assert result["primary_binding_constraint"] == "MAX_LEGS_PLUS_1"
    assert result["scenarios"]["team_to_score_plus_1"]["best_reachable"] == 80
    assert len({call[0] for call in calls}) == 1


def test_counterfactual_marks_mathematical_target_as_quality_rejected(monkeypatch):
    def solve(candidates, target, max_legs, market_cap, team_cap,
              under_cap=None, enforce_team_diversity=True,
              required_selection_ids=None):
        return (210.0 if team_cap > 2 else 100.0), .0001, candidates, "OPTIMAL"

    monkeypatch.setattr(slip_builder, "_verified_optimize", solve)
    pick = _pick(odds=210, confidence=.001)
    pick.update(selection_probability=.001, risk_adjusted_return=.21,
                trust={"trust_grade": "A"})
    result = _constraint_counterfactuals([pick], 200, 16, 6, 2, 2)
    relaxed = result["scenarios"]["team_to_score_plus_1"]
    assert relaxed["target_reached"] is True
    assert relaxed["passes_ev_policy"] is False
    assert relaxed["production_quality_target_reached"] is False


def test_week_builder_does_not_repeat_a_team_across_fixtures(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    first = _pick("first", odds=2, confidence=.82, market_group="goals_over_1_5")
    second = _pick("second", odds=2, confidence=.82, market="under_4_5",
                   market_group="goals_under_4_5")
    independent = _pick("third", odds=2, confidence=.80,
                        market="home_or_draw", market_group="double_chance")
    first["_fixture"].update(home={"name": "Shared FC"}, away={"name": "One FC"})
    second["_fixture"].update(home={"name": "Two FC"}, away={"name": "Shared FC"})
    independent["_fixture"].update(
        home={"name": "Three FC"}, away={"name": "Four FC"}
    )

    built = build_slip(
        4, pool=[first, second, independent], max_legs=2, market_cap=3
    )

    assert built["ok"], built
    teams = []
    for pick in built["picks"]:
        fixture = pick["_fixture"]
        teams.extend([fixture["home"]["name"], fixture["away"]["name"]])
    assert teams.count("Shared FC") <= 1


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


def test_strong_under_is_not_replaced_only_for_cosmetic_diversity(monkeypatch):
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
    assert built["under_leg_count"] >= 3
    selected = [pick["market"] for pick in built["picks"]
                if pick["market"].startswith("under_")]
    assert selected.count("under_3_5") <= 3
    assert selected.count("under_4_5") <= 3


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


def test_target_reaching_builder_ticket_is_refused_when_conservative_ev_is_poor(
    monkeypatch,
):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    markets = [
        ("over_1_5", "goals_over_1_5"),
        ("under_4_5", "goals_under_4_5"),
        ("home_or_draw", "double_chance"),
    ]
    board = [
        _pick(f"poor-{i}", odds=1.3, confidence=.65,
              market=markets[i % 3][0], market_group=markets[i % 3][1])
        for i in range(9)
    ]

    built = build_slip(10, pool=board, max_legs=9, market_cap=3)

    assert not built["ok"]
    assert built["result_status"] == "EXPECTED_RETURN_CAPPED"
    assert built["expected_return"] < built["minimum_expected_return"]


def test_builder_market_cap_scales_for_high_targets():
    assert slip_builder._market_cap_for_target(10) == 3
    assert slip_builder._market_cap_for_target(20) == 3
    assert slip_builder._market_cap_for_target(30) == 4
    assert slip_builder._market_cap_for_target(50) == 4
    assert slip_builder._market_cap_for_target(70) == 5
    assert slip_builder._market_cap_for_target(100) == 5
    assert slip_builder._market_cap_for_target(200) == 6


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
        built["picks"][0]["selection_probability"]
        * built["picks"][1]["selection_probability"],
        abs=1.1e-5,
    )

    assert {
        pick["match_id"]
        for pick in built["picks"]
    } == {
        "better-fixture",
        "anchor",
    }

def test_high_target_builder_can_use_four_quality_approved_picks_same_group(monkeypatch):
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

    assert built["ok"]
    assert built["result_status"] == "TARGET_REACHED"
    assert built["optimization_status"] == "OPTIMAL"
    assert built["legs"] == 4
    assert built["odds"] == pytest.approx(81.0)


def test_builder_cannot_use_deeper_public_alternative_to_manufacture_target(monkeypatch):
    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    fixture_alternatives = [
        _pick("shared", 1.10, .90, market="over_1_5", market_group="goals"),
        _pick("shared", 1.12, .88, market="under_4_5", market_group="under"),
        _pick("shared", 2.00, .70, market="home_or_draw", market_group="double_chance"),
    ]
    anchor = _pick("anchor-deep", 2.00, .82, market_group="other")
    built = build_slip(4, pool=fixture_alternatives + [anchor], max_legs=2,
                       market_cap=3)
    assert not built["ok"], built
    assert built["optimization_status"] == "OPTIMAL"
    assert built["result_status"] in {"QUALITY_CAPPED", "MAX_LEGS_CAPPED"}
    assert all(int(p.get("public_rank") or 99) <= 2
               for p in built.get("picks", []))


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


def test_capped_generate_exposes_safe_game_diagnostics_not_internal_picks(
        monkeypatch):
    pick = _pick("capped", odds=1.5, confidence=.8)
    monkeypatch.setattr(slip_builder, "_pool", lambda *a, **k: [pick])
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda **k: {})
    monkeypatch.setattr(slip_builder, "build_slip", lambda *a, **k: {
        "ok": False, "result_status": "QUALITY_CAPPED", "target": 10,
        "best_reachable": 1.5, "picks": [pick], "reason": "quality capped",
    })
    monkeypatch.setattr("leagues.picks.to_game", lambda p: {
        "match_id": p["match_id"], "fixture_rank": 1,
        "selection_reason_codes": ["PUBLIC_RANK_1"],
    })

    result = slip_builder.generate(10, horizon="week")

    assert result["status"] == "unavailable"
    assert "picks" not in result
    assert result["games"] == [{
        "match_id": "capped", "fixture_rank": 1,
        "selection_reason_codes": ["PUBLIC_RANK_1"],
    }]


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
