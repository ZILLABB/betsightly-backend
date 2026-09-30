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
        lambda horizon, force=False, refresh_sportybet=False, **kwargs: (
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




def test_original_v2_advanced_league_fixture_team_and_odds_filters(monkeypatch):
    premier = _pick(101, odds=1.20, fixture="fixture-premier")
    premier["_fixture"]["league"] = "Premier League"
    premier["_fixture"]["league_slug"] = "premier-league"
    premier["_fixture"]["home"] = {"id": "team-arsenal", "name": "Arsenal"}
    premier["_fixture"]["away"] = {"id": "team-everton", "name": "Everton"}

    laliga = _pick(102, odds=1.55, fixture="fixture-laliga")
    laliga["_fixture"]["league"] = "LaLiga"
    laliga["_fixture"]["league_slug"] = "laliga"
    laliga["_fixture"]["home"] = {"id": "team-barcelona", "name": "Barcelona"}
    laliga["_fixture"]["away"] = {"id": "team-sevilla", "name": "Sevilla"}

    serie_a = _pick(103, odds=2.10, fixture="fixture-serie-a")
    serie_a["_fixture"]["league"] = "Serie A"
    serie_a["_fixture"]["league_slug"] = "serie-a"
    serie_a["_fixture"]["home"] = {"id": "team-milan", "name": "Milan"}
    serie_a["_fixture"]["away"] = {"id": "team-roma", "name": "Roma"}

    picks = [premier, laliga, serie_a]
    _wire(monkeypatch, picks)

    included = builder_v2.list_candidates({
        "horizon": "7_days",
        "include_leagues": ["premier-league"],
    })
    assert [item["selection_id"] for item in included["candidates"]] == [
        premier["selection_id"]
    ]

    league_excluded = builder_v2.list_candidates({
        "horizon": "7_days",
        "exclude_leagues": ["LaLiga"],
    })
    assert laliga["selection_id"] not in {
        item["selection_id"] for item in league_excluded["candidates"]
    }

    fixture_excluded = builder_v2.list_candidates({
        "horizon": "7_days",
        "exclude_fixture_ids": ["fixture-serie-a"],
    })
    assert serie_a["selection_id"] not in {
        item["selection_id"] for item in fixture_excluded["candidates"]
    }

    team_name_excluded = builder_v2.list_candidates({
        "horizon": "7_days",
        "exclude_team_ids": ["Arsenal"],
    })
    assert premier["selection_id"] not in {
        item["selection_id"] for item in team_name_excluded["candidates"]
    }

    team_id_excluded = builder_v2.list_candidates({
        "horizon": "7_days",
        "exclude_team_ids": ["team-barcelona"],
    })
    assert laliga["selection_id"] not in {
        item["selection_id"] for item in team_id_excluded["candidates"]
    }

    odds_window = builder_v2.list_candidates({
        "horizon": "7_days",
        "min_odds": 1.40,
        "max_odds": 1.80,
    })
    assert [item["selection_id"] for item in odds_window["candidates"]] == [
        laliga["selection_id"]
    ]


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
        seen["preapproved_pool"] = kwargs["preapproved_pool"]
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
    assert seen["preapproved_pool"] is True
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
def test_target_mode_accepts_all_v2_horizons(monkeypatch):
    picks = [_pick(i) for i in range(5)]
    _wire(monkeypatch, picks)
    from leagues import slip_builder

    horizons = []

    def prepared(horizon, force=False, refresh_sportybet=False, **kwargs):
        horizons.append(horizon)
        return (
            {"__meta__": {"snapshot_id": "sporty-snap"}},
            list(picks),
            {"candidate_retrieval": 1},
        )

    monkeypatch.setattr(slip_builder, "prepared_bookable_pool", prepared)
    monkeypatch.setattr(
        slip_builder,
        "build_slip",
        lambda target, **kwargs: {
            "ok": False,
            "best_reachable": 1.5,
            "reason": "test",
        },
    )
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

    for horizon in ("today", "3_days", "7_days"):
        result = builder_v2.generate_v2({
            "mode": "target_odds",
            "target_odds": 50,
            "horizon": horizon,
        })
        assert result["requested_target"] == 50

    assert horizons == ["today", "3_days", "7_days"]




def test_manual_booking_does_not_force_full_sportybet_refresh(monkeypatch):
    picks = [_pick(1)]
    _wire(monkeypatch, picks)

    from leagues import slip_builder

    seen = {}

    def prepared(
        horizon,
        force=False,
        refresh_sportybet=False,
        **kwargs,
    ):
        seen["force"] = force
        seen["refresh_sportybet"] = refresh_sportybet
        return (
            {"__meta__": {"snapshot_id": "sporty-snap"}},
            list(picks),
            {"candidate_retrieval": 1},
        )

    monkeypatch.setattr(
        slip_builder,
        "prepared_bookable_pool",
        prepared,
    )

    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5"],
        "horizon": "7_days",
    })

    assert result["status"] == "success"
    assert seen["force"] is False
    assert seen["refresh_sportybet"] is False

    # Removing the expensive full catalogue crawl must not weaken the
    # exact-booking requirement.
    assert result["booking"]["booking_status"] == "FULL"
    assert result["booking"]["readback_validation"] == "PASSED"
    assert result["booking"]["share_code"]


def test_manual_started_selection_fails_without_code(monkeypatch):
    picks = [_pick(1)]
    _wire(monkeypatch, picks)
    from leagues import booking

    monkeypatch.setattr(
        booking,
        "create_booking",
        lambda *args, **kwargs: {
            "status": "started",
            "booking_status": "UNAVAILABLE",
            "share_code": None,
            "failure_category": "FIXTURE_STARTED",
            "reason": "fixture started",
        },
    )

    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5"],
        "horizon": "7_days",
    })

    assert result["status"] == "SELECTIONS_CHANGED"
    assert not (result.get("booking") or {}).get("share_code")


def test_manual_suspended_selection_fails_without_code(monkeypatch):
    picks = [_pick(1)]
    _wire(monkeypatch, picks)
    from leagues import booking

    monkeypatch.setattr(
        booking,
        "create_booking",
        lambda *args, **kwargs: {
            "status": "unavailable",
            "booking_status": "UNAVAILABLE",
            "share_code": None,
            "failure_category": "OUTCOME_SUSPENDED",
            "reason": "selection suspended",
        },
    )

    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5"],
        "horizon": "7_days",
    })

    assert result["status"] == "SELECTIONS_CHANGED"
    assert not (result.get("booking") or {}).get("share_code")


def test_manual_ignores_spoofed_client_price(monkeypatch):
    picks = [_pick(1, odds=1.5)]
    _wire(monkeypatch, picks)

    result = builder_v2.manual_build({
        "selection_ids": ["s1-over_1_5"],
        "horizon": "7_days",
        "odds": 99.0,
        "confidence": 0.99,
        "home_team": "Spoofed",
    })

    assert result["status"] == "success"
    assert result["odds"] == 1.5
    assert result["games"][0]["odds"] == 1.5


def test_v2_target_api_reuses_cached_generation(monkeypatch):
    import asyncio

    from leagues import api, builder_v2, daily_feed

    api._V2_TARGET_CACHE.clear()
    api._V2_TARGET_LOCKS.clear()
    calls = []

    monkeypatch.setattr(
        builder_v2,
        "generate_v2",
        lambda payload: calls.append(payload) or {
            "status": "success",
            "mode": "target_odds",
            "target": 10,
            "odds": 10.2,
            "games": [{"match_id": "m1"}],
            "booking": {
                "status": "active",
                "share_code": "CODE",
            },
        },
    )
    monkeypatch.setattr(
        api,
        "_start_builder_revision",
        lambda target, horizon, result: {
            **result,
            "builder_run_id": "run",
            "revision": 1,
            "edit_token": "token",
        },
    )
    monkeypatch.setattr(
        api,
        "_cached_target_result_is_reusable",
        lambda result, now=None: True,
    )
    monkeypatch.setattr(
        daily_feed,
        "_publish_date",
        lambda: "2099-01-01",
    )

    request = api.BuilderV2Request(
        mode="target_odds",
        target_odds=10,
        horizon="7_days",
    )
    first = asyncio.run(api.slip_builder_v2_generate(request))
    second = asyncio.run(api.slip_builder_v2_generate(request))

    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1




def test_v2_target_cache_invalidates_when_prepared_snapshot_changes(monkeypatch):
    import asyncio

    from leagues import api, builder_v2, daily_feed, engine

    api._V2_TARGET_CACHE.clear()
    api._V2_TARGET_LOCKS.clear()

    snapshot = {"id": "prepared-a"}
    calls = []

    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda **kwargs: {
            "ready": True,
            "board_snapshot_id": snapshot["id"],
            "generated_at": f"{snapshot['id']}-generated",
            "evaluated_fixture_count": 100,
        },
    )

    def fake_generate(payload):
        calls.append(snapshot["id"])
        return {
            "status": "success",
            "mode": "target_odds",
            "target": 10,
            "odds": 10.2 if snapshot["id"] == "prepared-a" else 10.4,
            "games": [{"match_id": snapshot["id"]}],
            "booking": {
                "status": "active",
                "share_code": f"CODE-{snapshot['id']}",
            },
        }

    monkeypatch.setattr(builder_v2, "generate_v2", fake_generate)
    monkeypatch.setattr(
        api,
        "_start_builder_revision",
        lambda target, horizon, result: {
            **result,
            "builder_run_id": f"run-{result['games'][0]['match_id']}",
            "revision": 1,
            "edit_token": "token",
        },
    )
    monkeypatch.setattr(
        api,
        "_cached_target_result_is_reusable",
        lambda result, now=None: True,
    )
    monkeypatch.setattr(
        daily_feed,
        "_publish_date",
        lambda: "2099-01-01",
    )

    request = api.BuilderV2Request(
        mode="target_odds",
        target_odds=10,
        horizon="7_days",
    )

    first = asyncio.run(api.slip_builder_v2_generate(request))
    same_board = asyncio.run(api.slip_builder_v2_generate(request))

    assert first["cached"] is False
    assert same_board["cached"] is True
    assert calls == ["prepared-a"]

    snapshot["id"] = "prepared-b"

    refreshed_board = asyncio.run(api.slip_builder_v2_generate(request))

    assert refreshed_board["cached"] is False
    assert refreshed_board["odds"] == 10.4
    assert refreshed_board["games"][0]["match_id"] == "prepared-b"
    assert calls == ["prepared-a", "prepared-b"]


def test_real_approval_rejects_sparse_extreme_live_price():
    from leagues.slip_builder import approved_builder_candidates

    pick = _pick(901, probability=.90, odds=4.90)
    pick.update({
        "calibration_sample": 500,
        "competition_historical_sample": 0,
        "base_rate_source": "global_default",
        "sportybet_availability": {
            "sportybet_available": True,
            "status": "BOOKABLE",
            "sportybet_odds": 4.90,
            "board_snapshot_id": "real-gate-snapshot",
        },
    })

    approved, rejections = approved_builder_candidates(
        [pick],
        require_bookable=True,
        include_all_eligible=True,
    )

    assert approved == []
    assert (
        rejections["sparse_competition_evidence"]
        or rejections["large_model_market_disagreement"]
        or rejections["SPARSE_COMPETITION_EVIDENCE"]
        or rejections["EXTREME_PRICE_MODEL_DISAGREEMENT"]
    )


def test_require_bookable_false_cannot_weaken_v2_server_gate(monkeypatch):
    from leagues import engine, slip_builder, sportybet

    unbookable = _pick(902)
    unbookable["bookable"] = False
    unbookable["sportybet_availability"] = {
        "sportybet_available": False,
        "status": "MARKET_NOT_FOUND",
    }

    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda **kwargs: {
            "ready": True,
            "stale": False,
            "board_snapshot_id": "prepared-snap",
        },
    )
    monkeypatch.setattr(
        slip_builder,
        "prepared_bookable_pool",
        lambda horizon, force=False, refresh_sportybet=False, **kwargs: (
            {"__meta__": {"snapshot_id": "sporty-snap"}},
            [unbookable],
            {"candidate_retrieval": 1},
        ),
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

    result = builder_v2.list_candidates({
        "horizon": "7_days",
        "require_bookable": False,
        "min_trust_grade": "D",
        "min_probability": 0,
    })

    assert result["status"] == "success"
    assert result["candidate_count"] == 0
    assert result["candidates"] == []
    assert result["selection_diagnostics"]["require_bookable_effective"] is True
    assert (
        result["selection_diagnostics"]["trust_rejection_reasons"]
        .get("sportybet_selection_not_exactly_bookable", 0)
        == 1
    )


def test_automatic_v2_modes_scrub_failed_readback_code(monkeypatch):
    picks = [_pick(903)]
    _wire(monkeypatch, picks)

    from leagues import booking
    monkeypatch.setattr(
        booking,
        "create_booking",
        lambda *args, **kwargs: {
            "status": "invalid",
            "booking_status": "VALIDATION_FAILED",
            "readback_validation": "FAILED",
            "share_code": "SHOULD_NOT_LEAK",
            "share_url": "https://unsafe.example",
            "failure_category": "READBACK_MISMATCH",
        },
    )

    for payload in (
        {"mode": "game_count", "game_count": 1, "horizon": "7_days"},
        {"mode": "strongest", "max_games": 1, "horizon": "7_days"},
    ):
        result = builder_v2.generate_v2(payload)
        assert result["status"] == "success"
        assert result["booking"]["share_code"] is None
        assert result["booking"]["share_url"] is None
        assert result["booking"]["actionable"] is False


def test_target_v2_scrubs_nonvalidated_booking_at_public_boundary(monkeypatch):
    picks = [_pick(904)]
    _wire(monkeypatch, picks)

    from leagues import booking, slip_builder

    monkeypatch.setattr(
        slip_builder,
        "build_slip",
        lambda target, **kwargs: {
            "ok": True,
            "result_status": "TARGET_REACHED",
            "optimization_status": "OPTIMAL",
            "picks": [picks[0]],
            "odds": 1.5,
            "legs": 1,
            "hit_probability": .75,
            "expected_return": 1.125,
            "avg_confidence": .75,
        },
    )
    monkeypatch.setattr(
        booking,
        "create_or_reuse_generated_booking",
        lambda *args, **kwargs: {
            "status": "invalid",
            "booking_status": "VALIDATION_FAILED",
            "readback_validation": "FAILED",
            "share_code": "SHOULD_NOT_LEAK",
            "share_url": "https://unsafe.example",
            "failure_category": "READBACK_MISMATCH",
        },
    )

    result = builder_v2.generate_v2({
        "mode": "target_odds",
        "target_odds": 2,
        "horizon": "7_days",
    })

    assert result["status"] == "success"
    assert result["booking"]["share_code"] is None
    assert result["booking"]["share_url"] is None
    assert result["booking"]["actionable"] is False

def test_game_count_balances_two_explicit_markets(monkeypatch):
    picks = (
        [
            _pick(
                i,
                market="over_1_5",
                probability=.90,
                fixture=f"o15-{i}",
            )
            for i in range(30)
        ]
        +
        [
            _pick(
                100 + i,
                market="over_2_5",
                probability=.72,
                fixture=f"o25-{i}",
            )
            for i in range(30)
        ]
    )
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 20,
        "horizon": "7_days",
        "markets": ["over_1_5", "over_2_5"],
    })

    assert result["status"] == "success"
    assert result["delivered_game_count"] == 20
    assert result["market_distribution"] == {
        "over_1_5": 10,
        "over_2_5": 10,
    }
    assert result["market_balance"]["applied"] is True
    assert result["market_balance"]["target_distribution"] == {
        "over_1_5": 10,
        "over_2_5": 10,
    }
    assert result["market_balance"]["shortfalls"] == {}
    assert result["market_balance"]["quality_floor_preserved"] is True


def test_game_count_backfills_when_one_requested_market_is_short(monkeypatch):
    picks = (
        [
            _pick(
                i,
                market="over_1_5",
                probability=.82,
                fixture=f"o15-{i}",
            )
            for i in range(30)
        ]
        +
        [
            _pick(
                100 + i,
                market="over_2_5",
                probability=.72,
                fixture=f"o25-{i}",
            )
            for i in range(4)
        ]
    )
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 20,
        "horizon": "7_days",
        "markets": ["over_1_5", "over_2_5"],
    })

    assert result["status"] == "success"
    assert result["delivered_game_count"] == 20
    assert result["market_distribution"] == {
        "over_1_5": 16,
        "over_2_5": 4,
    }
    assert result["market_balance"]["target_distribution"] == {
        "over_1_5": 10,
        "over_2_5": 10,
    }
    assert result["market_balance"]["shortfalls"] == {
        "over_2_5": 6,
    }
    assert result["market_balance"]["quality_floor_preserved"] is True


def test_game_count_strict_is_default_and_never_uses_other_markets(monkeypatch):
    picks = [_pick(i, market="over_1_5", fixture=f"requested-{i}") for i in range(2)] + [
        _pick(50 + i, market="under_4_5", fixture=f"fallback-{i}") for i in range(8)
    ]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({"mode": "game_count", "game_count": 10,
                                      "horizon": "7_days", "markets": ["over_1_5"]})
    assert result["delivered_game_count"] == 2
    assert result["markets_used"] == ["over_1_5"]
    assert result["fill_strategy"] == "strict_selected_markets"
    assert result["market_balance"]["fallback_market_leg_count"] == 0
    assert result["market_balance"]["fallback_market_distribution"] == {}


def test_game_count_selected_first_then_eligible_uses_approved_fallback(monkeypatch):
    picks = [_pick(i, market="over_1_5", fixture=f"requested-{i}") for i in range(2)] + [
        _pick(50 + i, market="under_4_5", fixture=f"fallback-{i}") for i in range(8)
    ]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({"mode": "game_count", "game_count": 10,
                                      "horizon": "7_days", "markets": ["over_1_5"],
                                      "fill_strategy": "selected_first_then_eligible"})
    assert result["delivered_game_count"] == 10
    balance = result["market_balance"]
    assert balance["requested_market_leg_count"] == 2
    assert balance["fallback_market_leg_count"] == 8
    assert balance["fallback_market_distribution"] == {"under_4_5": 8}
    assert balance["fallback_markets_used"] == ["under_4_5"]


def test_game_count_partial_fallback_reports_honest_shortfall(monkeypatch):
    picks = [_pick(i, market="home_win", fixture=f"requested-{i}") for i in range(14)] + [
        _pick(100 + i, market="under_4_5", fixture=f"fallback-a-{i}") for i in range(3)
    ] + [_pick(200 + i, market="home_or_draw", fixture=f"fallback-b-{i}") for i in range(5)]
    _wire(monkeypatch, picks)
    result = builder_v2.generate_v2({"mode": "game_count", "game_count": 50,
                                      "horizon": "7_days", "markets": ["home_win"],
                                      "fill_strategy": "selected_first_then_eligible"})
    balance = result["market_balance"]
    assert result["delivered_game_count"] == 22
    assert result["shortfall"] == 28
    assert balance["requested_market_leg_count"] == 14
    assert balance["fallback_market_leg_count"] == 8
    assert balance["fallback_market_distribution"] == {"home_or_draw": 5, "under_4_5": 3}
    assert balance["fallback_markets_used"] == ["home_or_draw", "under_4_5"]
    assert balance["requested_markets"] == ["home_win"]
    assert balance["requested_market_leg_count"] + balance["fallback_market_leg_count"] == result["delivered_game_count"]


def test_strongest_remains_quality_first_with_multiple_markets(monkeypatch):
    picks = (
        [
            _pick(
                i,
                market="over_1_5",
                probability=.90,
                fixture=f"strong-o15-{i}",
            )
            for i in range(10)
        ]
        +
        [
            _pick(
                100 + i,
                market="over_2_5",
                probability=.70,
                fixture=f"strong-o25-{i}",
            )
            for i in range(10)
        ]
    )
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "strongest",
        "max_games": 10,
        "horizon": "7_days",
        "markets": ["over_1_5", "over_2_5"],
    })

    assert result["status"] == "success"
    assert result["legs"] == 10
    assert result["market_distribution"] == {
        "over_1_5": 10,
    }
    assert "market_balance" not in result

def test_game_count_explicit_markets_request_all_eligible_candidates(monkeypatch):
    picks = [
        _pick(
            1,
            market="over_1_5",
            probability=.82,
            fixture="fixture-a",
        ),
        _pick(
            2,
            market="over_2_5",
            probability=.70,
            fixture="fixture-b",
        ),
    ]

    _wire(monkeypatch, picks)

    from leagues import slip_builder

    seen = {}

    def approved(
        pool,
        require_bookable=True,
        include_all_eligible=False,
    ):
        seen["include_all_eligible"] = include_all_eligible

        # Reproduce canonical behaviour:
        # the secondary market disappears unless the caller explicitly asks
        # for every eligible selection.
        if include_all_eligible:
            return list(pool), collections.Counter()

        return [
            pick
            for pick in pool
            if pick["market"] == "over_1_5"
        ], collections.Counter()

    monkeypatch.setattr(
        slip_builder,
        "approved_builder_candidates",
        approved,
    )

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 2,
        "horizon": "7_days",
        "markets": ["over_1_5", "over_2_5"],
    })

    assert seen["include_all_eligible"] is True
    assert result["status"] == "success"
    assert result["market_distribution"] == {
        "over_1_5": 1,
        "over_2_5": 1,
    }


def test_strongest_does_not_request_all_eligible_candidates(monkeypatch):
    picks = [
        _pick(
            1,
            market="over_1_5",
            probability=.90,
            fixture="fixture-a",
        ),
        _pick(
            2,
            market="over_2_5",
            probability=.70,
            fixture="fixture-b",
        ),
    ]

    _wire(monkeypatch, picks)

    from leagues import slip_builder

    seen = {}

    def approved(
        pool,
        require_bookable=True,
        include_all_eligible=False,
    ):
        seen["include_all_eligible"] = include_all_eligible
        return list(pool), collections.Counter()

    monkeypatch.setattr(
        slip_builder,
        "approved_builder_candidates",
        approved,
    )

    result = builder_v2.generate_v2({
        "mode": "strongest",
        "max_games": 2,
        "horizon": "7_days",
        "markets": ["over_1_5", "over_2_5"],
    })

    assert result["status"] == "success"
    assert seen["include_all_eligible"] is False


def test_game_count_protects_scarce_requested_market_from_abundant_fixture_conflict(
    monkeypatch,
):
    picks = [
        # Strongest Over 1.5 shares the only Home Win fixture.
        _pick(
            1,
            market="over_1_5",
            probability=.90,
            fixture="shared",
        ),
        # Alternative Over 1.5 can satisfy the O1.5 share.
        _pick(
            2,
            market="over_1_5",
            probability=.84,
            fixture="o15-alternative",
        ),
        # Only qualifying Home Win.
        _pick(
            3,
            market="home_win",
            probability=.74,
            odds=1.28,
            fixture="shared",
        ),
    ]

    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 2,
        "horizon": "7_days",
        "markets": ["over_1_5", "home_win"],
    })

    assert result["status"] == "success"
    assert result["delivered_game_count"] == 2
    assert result["market_distribution"] == {
        "over_1_5": 1,
        "home_win": 1,
    }

    assert result["market_balance"]["target_distribution"] == {
        "over_1_5": 1,
        "home_win": 1,
    }

    assert result["market_balance"]["shortfalls"] == {}
    assert result["market_balance"]["quality_floor_preserved"] is True


def test_game_count_reports_zero_candidate_market_reason(monkeypatch):
    picks = [
        _pick(
            1,
            market="over_1_5",
            probability=.80,
            fixture="o15-only",
        ),
    ]

    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 2,
        "horizon": "7_days",
        "markets": ["over_1_5", "away_win"],
    })

    availability = result["market_availability"]

    assert availability["over_1_5"]["approved"] == 1
    assert availability["over_1_5"]["selected"] == 1

    assert availability["away_win"] == {
        "target": 1,
        "raw": 0,
        "after_trust_and_policy": 0,
        "approved": 0,
        "selected": 0,
        "shortfall": 1,
        "primary_reason": "NO_RAW_CANDIDATES",
    }


def test_game_count_reports_policy_rejected_market_reason(monkeypatch):
    picks = [
        _pick(
            1,
            market="over_1_5",
            probability=.80,
            fixture="o15",
        ),
        _pick(
            2,
            market="under_3_5",
            probability=.80,
            fixture="u35",
        ),
    ]

    _wire(monkeypatch, picks)

    from leagues import slip_builder

    def approved(
        pool,
        require_bookable=True,
        include_all_eligible=False,
    ):
        return (
            [
                pick
                for pick in pool
                if pick["market"] != "under_3_5"
            ],
            collections.Counter({
                "insufficient_market_evidence": 1,
                "market_evidence_restricted": 1,
            }),
        )

    monkeypatch.setattr(
        slip_builder,
        "approved_builder_candidates",
        approved,
    )

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 2,
        "horizon": "7_days",
        "markets": ["over_1_5", "under_3_5"],
    })

    availability = result["market_availability"]

    assert availability["under_3_5"]["raw"] == 1
    assert availability["under_3_5"]["after_trust_and_policy"] == 0
    assert availability["under_3_5"]["approved"] == 0
    assert availability["under_3_5"]["selected"] == 0
    assert availability["under_3_5"]["primary_reason"] == (
        "TRUST_OR_MARKET_POLICY_REJECTED"
    )


def test_game_count_fallback_keeps_all_final_gates(monkeypatch):
    requested = _pick(
        1, market="over_1_5", probability=.80, fixture="requested"
    )
    low_probability = _pick(
        2, market="under_4_5", probability=.60, fixture="low-probability"
    )
    low_trust = _pick(
        3, market="under_4_5", probability=.80, fixture="low-trust"
    )
    low_trust["trust"]["trust_grade"] = "C"
    not_bookable = _pick(
        4, market="under_4_5", probability=.80, fixture="not-bookable"
    )
    not_bookable["bookable"] = False
    disabled = _pick(
        5, market="under_1_5", probability=.80, fixture="disabled"
    )
    restricted = _pick(
        6, market="under_2_5", probability=.80, fixture="restricted"
    )
    evidence_rejected = _pick(
        7, market="home_or_draw", probability=.80, fixture="evidence-rejected"
    )
    evidence_rejected["force_evidence_reject"] = True
    valid_fallback = _pick(
        8, market="home_or_draw", probability=.78, fixture="valid-fallback"
    )

    picks = [
        requested,
        low_probability,
        low_trust,
        not_bookable,
        disabled,
        restricted,
        evidence_rejected,
        valid_fallback,
    ]
    _wire(monkeypatch, picks)

    from leagues import slip_builder

    def approved(pool, require_bookable=True, include_all_eligible=False):
        return (
            [
                pick
                for pick in pool
                if not pick.get("force_evidence_reject")
            ],
            collections.Counter(
                {"insufficient_market_evidence": 1}
            ),
        )

    monkeypatch.setattr(
        slip_builder,
        "approved_builder_candidates",
        approved,
    )

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 8,
        "horizon": "7_days",
        "markets": ["over_1_5"],
        "fill_strategy": "selected_first_then_eligible",
    })

    assert result["status"] == "success"
    assert result["delivered_game_count"] == 2
    assert result["requested_market_leg_count"] == 1
    assert result["fallback_market_leg_count"] == 1
    assert result["fallback_market_distribution"] == {
        "home_or_draw": 1,
    }
    assert {
        game["selection_id"]
        for game in result["games"]
    } == {
        requested["selection_id"],
        valid_fallback["selection_id"],
    }


def test_game_count_requested_surplus_beats_stronger_fallback(monkeypatch):
    picks = [
        _pick(
            1, market="over_1_5", probability=.80, fixture="o15-1"
        ),
        _pick(
            2, market="over_1_5", probability=.79, fixture="o15-2"
        ),
        _pick(
            3, market="over_1_5", probability=.78, fixture="o15-3"
        ),
        _pick(
            10, market="home_win", probability=.74, fixture="home-win"
        ),
        _pick(
            20, market="under_4_5", probability=.95, fixture="fallback"
        ),
    ]
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 4,
        "horizon": "7_days",
        "markets": ["over_1_5", "home_win"],
        "fill_strategy": "selected_first_then_eligible",
    })

    assert result["delivered_game_count"] == 4
    assert result["fallback_market_leg_count"] == 0
    assert result["fallback_market_distribution"] == {}
    assert result["market_distribution"] == {
        "over_1_5": 3,
        "home_win": 1,
    }


def test_game_count_fallback_preserves_fixture_and_team_diversity(monkeypatch):
    requested = _pick(
        1, market="over_1_5", probability=.82, fixture="shared-fixture"
    )
    duplicate_fixture = _pick(
        2, market="under_4_5", probability=.90, fixture="shared-fixture"
    )
    duplicate_team = _pick(
        3, market="under_4_5", probability=.88, fixture="other-fixture"
    )
    duplicate_team["_fixture"]["home"]["name"] = (
        requested["_fixture"]["home"]["name"]
    )
    valid_fallback = _pick(
        4, market="under_4_5", probability=.78, fixture="valid-fixture"
    )

    _wire(
        monkeypatch,
        [requested, duplicate_fixture, duplicate_team, valid_fallback],
    )

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 3,
        "horizon": "7_days",
        "markets": ["over_1_5"],
        "fill_strategy": "selected_first_then_eligible",
    })

    assert result["delivered_game_count"] == 2
    assert [
        game["selection_id"]
        for game in result["games"]
    ] == [
        requested["selection_id"],
        valid_fallback["selection_id"],
    ]


def test_game_count_fallback_keeps_requested_market_availability_truthful(
    monkeypatch,
):
    picks = [
        _pick(
            1, market="home_win", probability=.76, fixture="requested"
        ),
        _pick(
            10, market="under_4_5", probability=.80, fixture="fallback-1"
        ),
        _pick(
            11, market="under_4_5", probability=.79, fixture="fallback-2"
        ),
        _pick(
            12, market="home_or_draw", probability=.78, fixture="fallback-3"
        ),
    ]
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 4,
        "horizon": "7_days",
        "markets": ["home_win"],
        "fill_strategy": "selected_first_then_eligible",
    })

    assert result["delivered_game_count"] == 4
    assert result["requested_market_leg_count"] == 1
    assert result["fallback_market_leg_count"] == 3
    assert result["market_balance"]["requested_markets"] == ["home_win"]
    assert result["market_balance"]["target_distribution"] == {
        "home_win": 4,
    }
    assert result["market_availability"]["home_win"]["selected"] == 1
    assert result["market_availability"]["home_win"]["target"] == 4
    assert result["market_availability"]["home_win"]["shortfall"] == 3


def test_game_count_booking_receives_exact_requested_plus_fallback_set(
    monkeypatch,
):
    picks = [
        _pick(
            1, market="over_1_5", probability=.80, fixture="requested"
        ),
        _pick(
            2, market="under_4_5", probability=.79, fixture="fallback-1"
        ),
        _pick(
            3, market="home_or_draw", probability=.78, fixture="fallback-2"
        ),
    ]
    _wire(monkeypatch, picks)

    from leagues import booking

    captured = {}

    def create_booking(games, board, **kwargs):
        captured["selection_ids"] = [
            game["selection_id"]
            for game in games
        ]
        return {
            "status": "active",
            "booking_status": "FULL",
            "readback_validation": "PASSED",
            "share_code": "CODE",
            "share_url": "https://example.test",
        }

    monkeypatch.setattr(booking, "create_booking", create_booking)

    result = builder_v2.generate_v2({
        "mode": "game_count",
        "game_count": 3,
        "horizon": "7_days",
        "markets": ["over_1_5"],
        "fill_strategy": "selected_first_then_eligible",
    })

    assert captured["selection_ids"] == [
        game["selection_id"]
        for game in result["games"]
    ]
    assert result["requested_market_leg_count"] == 1
    assert result["fallback_market_leg_count"] == 2


def test_game_count_fallback_is_deterministic(monkeypatch):
    picks = [
        _pick(
            1, market="over_1_5", probability=.80, fixture="requested"
        ),
        _pick(
            2, market="under_4_5", probability=.79, fixture="fallback-1"
        ),
        _pick(
            3, market="home_or_draw", probability=.78, fixture="fallback-2"
        ),
        _pick(
            4, market="away_or_draw", probability=.77, fixture="fallback-3"
        ),
    ]
    _wire(monkeypatch, picks)

    options = {
        "mode": "game_count",
        "game_count": 4,
        "horizon": "7_days",
        "markets": ["over_1_5"],
        "fill_strategy": "selected_first_then_eligible",
    }

    first = builder_v2.generate_v2(options)
    second = builder_v2.generate_v2(options)

    assert [
        game["selection_id"]
        for game in first["games"]
    ] == [
        game["selection_id"]
        for game in second["games"]
    ]
    assert (
        first["fallback_market_distribution"]
        == second["fallback_market_distribution"]
    )
    assert first["fallback_markets_used"] == second["fallback_markets_used"]


def test_fill_strategy_does_not_change_strongest_mode(monkeypatch):
    picks = [
        _pick(1, probability=.85, fixture="one"),
        _pick(2, probability=.80, fixture="two"),
    ]
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "strongest",
        "max_games": 2,
        "horizon": "7_days",
        "fill_strategy": "not-a-game-count-strategy",
    })

    assert result["status"] == "success"
    assert result["legs"] == 2
    assert "market_balance" not in result


def test_all_four_modes_share_frozen_board_and_exact_booking(monkeypatch):
    from leagues import booking
    picks = [_pick(i, probability=.92, odds=1.5) for i in range(8)]
    _wire(monkeypatch, picks)
    monkeypatch.setattr(booking, "create_or_reuse_generated_booking",
                        lambda games, board, **kw: booking.create_booking(games, board))
    ids = [pick["selection_id"] for pick in picks[:3]]
    results = [
        builder_v2.generate_v2({"mode": "target_odds", "target_odds": 2, "horizon": "7_days"}),
        builder_v2.generate_v2({"mode": "game_count", "game_count": 3, "horizon": "7_days"}),
        builder_v2.generate_v2({"mode": "strongest", "max_games": 3, "horizon": "7_days"}),
        builder_v2.manual_build({"selection_ids": ids, "horizon": "7_days"}),
    ]
    for result in results:
        assert result["status"] == "success", result
        assert result["board"]["board_snapshot_id"] == "prepared-snap"
        fixtures = [game["match_id"] for game in result["games"]]
        assert len(fixtures) == len(set(fixtures))
        assert set(fixtures) <= {p["match_id"] for p in picks if p["bookable"]}
        assert result["booking"]["booking_status"] == "FULL"
        assert result["booking"]["readback_validation"] == "PASSED"
    assert [game["selection_id"] for game in results[-1]["games"]] == ids



def test_build_another_prefers_fresh_selections_when_sufficient(monkeypatch):
    picks = [
        _pick(1, probability=.90),
        _pick(2, probability=.85),
        _pick(3, probability=.80),
    ]
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "strongest",
        "max_games": 1,
        "horizon": "today",
        "_build_another": True,
        "_recent_exposure": {
            "history_ticket_count": 2,
            "exact_selection_ids": [
                picks[0]["selection_id"],
            ],
            "recent_fixture_ids": [
                picks[1]["match_id"],
            ],
        },
    })

    assert result["status"] == "success"
    assert result["games"][0]["selection_id"] == picks[2]["selection_id"]
    assert result["diversification"]["strategy_used"] == "fresh"
    assert result["diversification"]["repeated_selection_count"] == 0


def test_build_another_allows_qualified_repeat_when_needed(monkeypatch):
    picks = [
        _pick(1, probability=.90),
        _pick(2, probability=.85),
        _pick(3, probability=.80),
    ]
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "strongest",
        "max_games": 3,
        "horizon": "today",
        "_build_another": True,
        "_recent_exposure": {
            "history_ticket_count": 2,
            "exact_selection_ids": [
                picks[0]["selection_id"],
            ],
            "recent_fixture_ids": [
                picks[1]["match_id"],
            ],
        },
    })

    assert result["status"] == "success"
    assert result["legs"] == 3
    assert result["diversification"]["strategy_used"] == "qualified_repeat_fallback"
    assert result["diversification"]["repeated_selection_count"] == 1
    assert result["diversification"]["unavoidable_reuse_count"] == 1


def test_normal_builder_is_unchanged_by_diversification_helpers(monkeypatch):
    picks = [_pick(i) for i in range(5)]
    _wire(monkeypatch, picks)

    result = builder_v2.generate_v2({
        "mode": "strongest",
        "max_games": 3,
        "horizon": "today",
    })

    assert result["status"] == "success"
    assert result["legs"] == 3
    assert result["diversification"]["build_another"] is False
    assert result["diversification"]["strategy_used"] == "normal"
