import inspect

from leagues import daily_feed, engine, slip_builder
from leagues.sportybet_shadow_gate import production_bridge_candidates


def _pick(*, history=60, rar=1.03, safe=True):
    return {
        "match_id": "sportybet-shadow:fixture-1",
        "market": "over_1_5",
        "prediction": "Over 1.5 Goals",
        "selection_probability": .73,
        "risk_adjusted_return": rar,
        "market_trust_state": "TRUSTED",
        "market_floor_eligible": True,
        "safe_tier_eligible": safe,
        "bookable": True,
        "odds_are_real": True,
        "odds": 1.42,
        "_fixture": {
            "match_id": "sportybet-shadow:fixture-1",
            "league": "EFL League One",
            "league_slug": "eng.3",
            "competition_type": "LEAGUE",
            "competition_historical_sample": history,
            "_shadow_supplemental": True,
        },
    }


def test_production_bridge_requires_flag_complete_board_and_production():
    pick = _pick()

    candidates, report = production_bridge_candidates(
        [pick], board_complete=True,
        environment="production", feature_flag=False,
    )
    assert candidates == []
    assert report["status"] == "diagnostic_ready_feature_flag_off"
    assert report["eligible_candidate_count"] == 1
    assert report["production_merge_allowed"] is False
    assert report["activation_blocked_by_feature_flag"] is True

    candidates, report = production_bridge_candidates(
        [pick], board_complete=False,
        environment="production", feature_flag=True,
    )
    assert candidates == []
    assert report["status"] == "sportybet_board_incomplete"

    candidates, report = production_bridge_candidates(
        [pick], board_complete=True,
        environment="staging", feature_flag=True,
    )
    assert len(candidates) == 1
    assert report["status"] == "ready_for_staging_preview"
    assert report["bridge_mode"] == "staging_preview"


def test_production_bridge_admits_only_history_ready_positive_value_pick():
    source = _pick()
    candidates, report = production_bridge_candidates(
        [source], board_complete=True,
        environment="production", feature_flag=True,
    )
    assert report["status"] == "ready_for_production_merge"
    assert len(candidates) == 1
    assert candidates[0]["_production_supplemental"] is True
    assert candidates[0] is not source

    thin, thin_report = production_bridge_candidates(
        [_pick(history=12)], board_complete=True,
        environment="production", feature_flag=True,
    )
    assert thin == []
    assert thin_report["rejection_reason_counts"][
        "INSUFFICIENT_COMPETITION_HISTORY"
    ] == 1

    negative, negative_report = production_bridge_candidates(
        [_pick(rar=.98)], board_complete=True,
        environment="production", feature_flag=True,
    )
    assert negative == []
    assert negative_report["rejection_reason_counts"][
        "NEGATIVE_MODEL_VALUE"
    ] == 1


def test_engine_wires_production_candidates_into_prediction_and_builder_pool():
    source = inspect.getsource(engine._build_pipeline)
    assert '"_production_candidates"' in source
    assert "sportybet_production_merged" in source
    assert "all_picks.extend(" in source
    assert "sportybet_builder_picks" in source
    assert '"prediction_supply"' in source


def test_builder_does_not_rebuild_unapproved_supplemental_markets():
    source = inspect.getsource(slip_builder._pool)
    marker = 'if fixture.get("_production_supplemental"):'
    assert marker in source
    assert source.index(marker) < source.index(
        'model = fixture.get("_model")'
    )


def test_rollover_publication_precedes_exposure_in_both_action_paths():
    morning = inspect.getsource(daily_feed.build_daily_accumulators)
    live = inspect.getsource(daily_feed.build_bookable_now)

    morning_gate = morning.index(
        '_rollover_preallocation_card = {"rollover": rollover}'
    )
    morning_exposure = morning.index("fixture_uses = {", morning_gate)
    assert morning_gate < morning_exposure

    live_gate = live.index(
        '_live_rollover_preallocation_card = {"rollover": rollover}'
    )
    live_exposure = live.index("fixture_uses = {", live_gate)
    assert live_gate < live_exposure


def test_same_day_recovery_reserves_existing_portfolio_before_selection():
    source = inspect.getsource(daily_feed.recover_today_empty_tiers)
    assert "reserved_fixture_ids" in source
    assert "reserved_selection_ids" in source
    assert "reserved_teams" in source
    assert "recovery_available" in source
    assert 'recovery.get("status") == "RECOVERED"' in source


def test_engine_requests_full_bounded_supplemental_readiness_window():
    source = inspect.getsource(engine._build_pipeline)
    marker = "sportybet.shadow_supplemental_readiness("
    start = source.index(marker)
    call_window = source[start:start + 1000]
    assert "sample_limit=120" in call_window


def test_promoted_supplemental_fixture_settlement_does_not_require_espn_match_id():
    from leagues.results_checker import (
        _lookup_settlement_score,
        _normalize_name,
    )

    promoted_pick = {
        "match_id": "sportybet-shadow:sr:match:123",
        "home_team": "Alpha FC",
        "away_team": "Beta United",
        "date": "2026-10-07T18:00:00+00:00",
    }

    score_key = "|".join(
        (
            _normalize_name(promoted_pick["home_team"]),
            _normalize_name(promoted_pick["away_team"]),
            promoted_pick["date"][:10],
        )
    )

    scores = {
        score_key: {
            "home": "Alpha FC",
            "away": "Beta United",
            "home_score": 2,
            "away_score": 1,
            "completed": True,
        }
    }

    score = _lookup_settlement_score(
        scores,
        promoted_pick["home_team"],
        promoted_pick["away_team"],
        promoted_pick["date"][:10],
    )

    assert score is not None
    assert score["home_score"] == 2
    assert score["away_score"] == 1


def test_production_bridge_reports_rejections_while_flag_is_off():
    candidates, report = production_bridge_candidates(
        [_pick(safe=False)],
        board_complete=True,
        environment="production",
        feature_flag=False,
    )

    assert candidates == []
    assert report["status"] == "diagnostic_no_eligible_candidates"
    assert report["eligible_candidate_count"] == 0
    assert report["production_merge_allowed"] is False
    assert report["activation_blocked_by_feature_flag"] is True
    assert (
        report["rejection_reason_counts"][
            "SAFE_TIER_EVIDENCE_NOT_READY"
        ]
        == 1
    )
