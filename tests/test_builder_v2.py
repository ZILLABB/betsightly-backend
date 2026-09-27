import collections

from leagues import builder_v2


def _pick(index, *, market="over_1_5", probability=.75, odds=1.5, fixture=None):
    fixture_id = fixture or f"m{index}"
    return {
        "selection_id": f"s{index}-{market}",
        "match_id": fixture_id,
        "market": market,
        "market_group": "goals",
        "prediction": "Over 1.5",
        "confidence": probability,
        "odds": odds,
        "odds_are_real": True,
        "odds_provider": "SportyBet",
        "bookable": True,
        "risk_adjusted_return": probability * odds,
        "quality_score": probability * 100,
        "market_trust_state": "TRUSTED",
        "trust": {
            "trust_grade": "A",
            "trust_score": 90,
            "evidence_adjusted_probability": probability,
            "lower_reliability_bound": max(.01, probability - .02),
            "evidence_strength": 1.0,
        },
        "_fixture": {
            "home": {"name": f"Home {index}"},
            "away": {"name": f"Away {index}"},
            "league": "League",
            "league_slug": "league",
            "commence_time": "2099-01-01T12:00:00Z",
        },
        "_model": {"expected_goals": {"home": 1.5, "away": 1.2}},
    }


def _wire(monkeypatch, picks):
    from leagues import booking, engine, picks as picks_module, slip_builder, sportybet

    monkeypatch.setattr(
        slip_builder,
        "prepared_bookable_pool",
        lambda horizon, force=False, refresh_sportybet=False: (
            {"__meta__": {"snapshot_id": "sporty-snap"}},
            list(picks),
            {"candidate_retrieval": 1},
        ),
    )
    monkeypatch.setattr(
        slip_builder,
        "approved_builder_candidates",
        lambda pool, require_bookable=True, include_all_eligible=False: (
            list(pool), collections.Counter()
        ),
    )
    monkeypatch.setattr(
        picks_module,
        "to_game",
        lambda pick: {
            "selection_id": pick["selection_id"],
            "match_id": pick["match_id"],
            "home_team": pick["_fixture"]["home"]["name"],
            "away_team": pick["_fixture"]["away"]["name"],
            "league": pick["_fixture"]["league"],
            "kickoff": pick["_fixture"]["commence_time"],
            "market": pick["market"],
            "prediction": pick["prediction"],
            "odds": pick["odds"],
            "confidence": pick["confidence"],
        },
    )
    monkeypatch.setattr(
        booking,
        "create_booking",
        lambda *args, **kwargs: {
            "status": "active",
            "booking_status": "FULL",
            "readback_validation": "PASSED",
            "share_code": "CODE",
            "share_url": "https://example.test",
        },
    )
    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda **kwargs: {
            "ready": True,
            "board_snapshot_id": "prepared-snap",
            "generated_at": "2099-01-01T00:00:00Z",
            "age_seconds": 1,
            "degraded": False,
            "complete": True,
        },
    )
    monkeypatch.setattr(
        sportybet,
        "board_metadata",
        lambda board: {
            "snapshot_id": "sporty-snap",
            "is_complete": True,
            "generated_at": "2099-01-01T00:00:00Z",
        },
    )


def test_game_count_never_exceeds_requested(monkeypatch):
    picks = [_pick(i) for i in range(30)]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 20, "horizon": "7_days",
    })
    assert result["status"] == "success"
    assert result["delivered_game_count"] == 20
    assert result["legs"] == 20


def test_game_count_shortfall_is_honest(monkeypatch):
    picks = [_pick(i) for i in range(17)]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 50, "horizon": "7_days",
    })
    assert result["delivered_game_count"] == 17
    assert result["shortfall"] == 33
    assert result["shortfall_reason"]


def test_market_filter_is_exact(monkeypatch):
    picks = [
        _pick(1, market="over_1_5"),
        _pick(2, market="over_2_5"),
    ]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 10, "horizon": "today",
        "markets": ["over_1_5"],
    })
    assert result["status"] == "success"
    assert {game["market"] for game in result["games"]} == {"over_1_5"}


def test_user_probability_filter_cannot_lower_system_floor(monkeypatch):
    picks = [_pick(1, probability=.60), _pick(2, probability=.70)]
    _wire(monkeypatch, picks)
    result = builder_v2.list_candidates({
        "horizon": "today", "min_probability": .50,
    })
    assert result["selection_diagnostics"]["effective_min_probability"] == .65
    assert [candidate["selection_id"] for candidate in result["candidates"]] == ["s2-over_1_5"]


def test_strongest_is_deterministic_and_one_fixture_once(monkeypatch):
    picks = [
        _pick(1, probability=.80, fixture="same"),
        _pick(2, probability=.75, fixture="same"),
        _pick(3, probability=.78),
    ]
    _wire(monkeypatch, picks)
    first = builder_v2.generate_v2({
        "mode": "strongest", "max_games": 10, "horizon": "7_days",
    })
    second = builder_v2.generate_v2({
        "mode": "strongest", "max_games": 10, "horizon": "7_days",
    })
    assert [g["selection_id"] for g in first["games"]] == [g["selection_id"] for g in second["games"]]
    assert len({g["match_id"] for g in first["games"]}) == len(first["games"])


def test_manual_rejects_51_without_touching_board():
    result = builder_v2.manual_build({
        "selection_ids": [f"s{i}" for i in range(51)],
        "horizon": "7_days",
    })
    assert result["status"] == "error"
    assert "50" in result["reason"]


def test_manual_unknown_selection_is_not_silently_replaced(monkeypatch):
    picks = [_pick(1)]
    _wire(monkeypatch, picks)
    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5", "missing"],
        "horizon": "7_days",
    })
    assert result["status"] == "SELECTIONS_CHANGED"
    assert result["invalid_selections"][0]["selection_id"] == "missing"


def test_manual_duplicate_fixture_is_rejected(monkeypatch):
    picks = [
        _pick(1, market="over_1_5", fixture="same"),
        _pick(2, market="over_2_5", fixture="same"),
    ]
    _wire(monkeypatch, picks)
    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5", "s2-over_2_5"],
        "horizon": "7_days",
    })
    assert result["status"] == "SELECTIONS_CHANGED"
    assert result["invalid_selections"][0]["reason"] == "DUPLICATE_FIXTURE"


def test_manual_code_requires_passed_readback(monkeypatch):
    picks = [_pick(1)]
    _wire(monkeypatch, picks)
    from leagues import booking
    monkeypatch.setattr(
        booking,
        "create_booking",
        lambda *args, **kwargs: {
            "status": "failed",
            "booking_status": "UNAVAILABLE",
            "readback_validation": "FAILED",
            "share_code": "SHOULD_NOT_LEAK",
            "failure_category": "READBACK_MISMATCH",
            "reason": "readback mismatch",
        },
    )
    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5"],
        "horizon": "7_days",
    })
    assert result["status"] == "SELECTIONS_CHANGED"
    assert not (result.get("booking") or {}).get("share_code")


def test_target_mode_keeps_existing_max_legs(monkeypatch):
    picks = [_pick(i) for i in range(5)]
    _wire(monkeypatch, picks)
    from leagues import slip_builder
    seen = {}

    def fake_build(target, **kwargs):
        seen["max_legs"] = kwargs["max_legs"]
        return {"ok": False, "best_reachable": 1.5, "reason": "test"}

    monkeypatch.setattr(slip_builder, "build_slip", fake_build)
    monkeypatch.setattr(
        slip_builder,
        "_public_result_from_build",
        lambda target, horizon, built, board: {
            "status": "unavailable",
            "target": target,
            "best_reachable": built["best_reachable"],
            "reason": built["reason"],
            "games": [],
        },
    )
    result = builder_v2.generate_v2({
        "mode": "target_odds", "target_odds": 50, "horizon": "7_days",
    })
    assert seen["max_legs"] == slip_builder.MAX_LEGS == 16
    assert result["requested_target"] == 50


def test_game_count_50_can_deliver_50(monkeypatch):
    picks = [_pick(i) for i in range(50)]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 50, "horizon": "7_days",
    })
    assert result["status"] == "success"
    assert result["delivered_game_count"] == 50
    assert result["legs"] == 50


def test_manual_accepts_50_approved_selections(monkeypatch):
    picks = [_pick(i) for i in range(50)]
    _wire(monkeypatch, picks)
    result = builder_v2.manual_build({
        "selection_ids": [pick["selection_id"] for pick in picks],
        "horizon": "7_days",
    })
    assert result["status"] == "success"
    assert result["legs"] == 50
    assert result["booking"]["readback_validation"] == "PASSED"


def test_cold_prepared_board_does_not_fall_through_to_pool(monkeypatch):
    from leagues import engine, slip_builder

    called = {"pool": False}
    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda **kwargs: {"ready": False, "stale": False},
    )
    monkeypatch.setattr(
        engine,
        "start_prepared_board_refresh",
        lambda **kwargs: True,
    )

    def forbidden_pool(*args, **kwargs):
        called["pool"] = True
        raise AssertionError("interactive V2 must not cold-start the pipeline")

    monkeypatch.setattr(slip_builder, "prepared_bookable_pool", forbidden_pool)

    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 5, "horizon": "7_days",
    })

    assert result["status"] == "unavailable"
    assert result["reason"] == "board_refreshing"
    assert result["refresh_started"] is True
    assert called["pool"] is False


def test_stale_prepared_board_serves_last_safe_board(monkeypatch):
    picks = [_pick(1)]
    _wire(monkeypatch, picks)
    from leagues import engine

    refreshes = []
    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda **kwargs: {
            "ready": True,
            "stale": True,
            "board_snapshot_id": "old-safe-board",
        },
    )
    monkeypatch.setattr(
        engine,
        "start_prepared_board_refresh",
        lambda **kwargs: refreshes.append(kwargs) or True,
    )

    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 1, "horizon": "today",
    })

    assert result["status"] == "success"
    assert refreshes
    assert result["selection_diagnostics"]["prepared_board_stale"] is True


def test_manual_browsing_requests_all_eligible_markets(monkeypatch):
    picks = [
        _pick(1, market="over_1_5", fixture="same"),
        _pick(2, market="over_2_5", fixture="same"),
    ]
    _wire(monkeypatch, picks)
    from leagues import slip_builder

    seen = {}

    def approved(pool, require_bookable=True, include_all_eligible=False):
        seen["include_all_eligible"] = include_all_eligible
        return list(pool), collections.Counter()

    monkeypatch.setattr(slip_builder, "approved_builder_candidates", approved)

    result = builder_v2.list_candidates({"horizon": "today"})

    assert result["status"] == "success"
    assert seen["include_all_eligible"] is True
    assert len(result["candidates"]) == 2
    assert sum(bool(item["recommended_for_fixture"]) for item in result["candidates"]) == 1
