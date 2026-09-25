"""Settlement coverage for every market the prediction engine publishes."""

import json
from datetime import datetime, timezone

import pytest

from leagues.results_checker import (
    _evaluate_pick, _lookup_score, _missing_result_expired, _rollover_day_status,
    settle_builder_predictions, settle_published_slips,
)


@pytest.mark.parametrize(
    "market,score,expected",
    [
        ("home_win", (2, 1), "won"),
        ("away_win", (2, 1), "lost"),
        ("draw", (1, 1), "won"),
        ("home_or_draw", (1, 1), "won"),
        ("away_or_draw", (2, 1), "lost"),
        ("home_or_away", (0, 0), "lost"),
        ("over_1_5", (1, 1), "won"),
        ("over_2_5", (1, 1), "lost"),
        ("under_1_5", (1, 0), "won"),
        ("under_2_5", (1, 1), "won"),
        ("under_3_5", (2, 1), "won"),
        ("under_4_5", (3, 1), "won"),
        ("over_4_5", (3, 2), "won"),
        ("home_over_0_5", (1, 0), "won"),
        ("home_over_1_5", (1, 0), "lost"),
        ("away_over_0_5", (0, 1), "won"),
        ("away_over_1_5", (0, 1), "lost"),
        ("home_under_0_5", (0, 2), "won"),
        ("home_under_1_5", (2, 0), "lost"),
        ("away_under_0_5", (2, 0), "won"),
        ("away_under_1_5", (0, 2), "lost"),
        ("btts_yes", (1, 1), "won"),
        ("btts_no", (1, 0), "won"),
        ("dnb_home", (2, 1), "won"),
        ("dnb_away", (2, 1), "lost"),
        ("dnb_home", (1, 1), "void"),
    ],
)
def test_specific_market_keys_settle_correctly(market, score, expected):
    pick = {"market": market, "home_team": "Home", "away_team": "Away"}
    assert _evaluate_pick(pick, *score) == expected


def test_score_lookup_prefers_the_exact_fixture_date():
    scores = {
        "home|away|2026-09-01": {"home_score": 1, "away_score": 0},
        "home|away|2026-09-08": {"home_score": 0, "away_score": 2},
        "home|away": {"home_score": 1, "away_score": 0},
    }
    assert _lookup_score(scores, "Home", "Away", "2026-09-08") == {
        "home_score": 0,
        "away_score": 2,
    }


def test_score_lookup_with_date_never_uses_a_different_fixture_date():
    scores = {
        "home|away|2026-09-01": {"home_score": 1, "away_score": 0},
        "home|away": {"home_score": 1, "away_score": 0},
    }
    assert _lookup_score(scores, "Home", "Away", "2026-09-08") is None


def test_score_lookup_without_date_can_use_legacy_pair_key():
    scores = {
        "home|away": {"home_score": 2, "away_score": 1},
    }
    assert _lookup_score(scores, "Home", "Away") == {
        "home_score": 2,
        "away_score": 1,
    }


def test_score_lookup_uses_known_alias_on_the_same_date():
    scores = {
        "united states|canada|2026-09-08": {
            "home_score": 2,
            "away_score": 0,
        },
    }
    assert _lookup_score(scores, "USA", "Canada", "2026-09-08") == {
        "home_score": 2,
        "away_score": 0,
    }


def test_rollover_market_key_takes_precedence_over_diversity_group():
    pick = {
        "market": "goals",
        "market_key": "under_4_5",
        "prediction": "Under 4.5 Goals",
    }
    assert _evaluate_pick(pick, 3, 1) == "won"
    assert _evaluate_pick(pick, 4, 1) == "lost"


def test_legacy_goals_row_can_still_settle_from_its_label():
    pick = {"market": "goals", "prediction": "Under 3.5 Goals"}
    assert _evaluate_pick(pick, 2, 1) == "won"


def test_missing_result_only_voids_after_the_reporting_grace():
    pick = {"commence_time": "2026-08-30T20:00:00Z"}
    assert not _missing_result_expired(
        pick, datetime(2026, 9, 1, 19, 59, tzinfo=timezone.utc))
    assert _missing_result_expired(
        pick, datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "legs,expected",
    [
        (["won", "won"], "won"),
        (["won", "void"], "won"),
        (["void", "void"], "void"),
        (["won", "pending"], "pending"),
        (["won", "lost", "void"], "lost"),
    ],
)
def test_rollover_day_settlement_handles_void_legs(legs, expected):
    assert _rollover_day_status(legs) == expected


def test_builder_settlement_routes_through_canonical_market_evaluator(monkeypatch):
    picks = [
        {"home_team": "Alpha", "away_team": "Beta", "market": "dnb_home",
         "kickoff": "2026-09-08T18:00:00Z"},
        {"home_team": "Gamma", "away_team": "Delta", "market": "under_2_5",
         "kickoff": "2026-09-08T19:00:00Z"},
    ]
    monkeypatch.setattr(
        "leagues.builder_runs.pending_predictions",
        lambda: [{"selection_fingerprint": "build-1", "picks": json.dumps(picks)}],
    )
    settled = {}

    def capture(fingerprint, outcomes, details=None):
        settled.update(fingerprint=fingerprint, outcomes=outcomes)
        return "won"

    monkeypatch.setattr("leagues.builder_runs.settle_prediction", capture)
    scores = {
        "alpha|beta|2026-09-08": {"home_score": 1, "away_score": 1},
        "gamma|delta|2026-09-08": {"home_score": 1, "away_score": 1},
    }
    result = settle_builder_predictions(
        scores=scores, now=datetime(2026, 9, 9, tzinfo=timezone.utc)
    )
    assert settled == {"fingerprint": "build-1", "outcomes": ["void", "won"]}
    assert result["won"] == 1


def test_missing_builder_score_stays_pending_even_after_grace(monkeypatch):
    pick = {"home_team": "Alpha", "away_team": "Beta", "market": "over_1_5",
            "kickoff": "2026-09-01T18:00:00Z"}
    monkeypatch.setattr("leagues.builder_runs.pending_predictions", lambda: [
        {"selection_fingerprint": "missing", "picks": json.dumps([pick])}
    ])
    observed = []
    monkeypatch.setattr("leagues.builder_runs.settle_prediction",
                        lambda fingerprint, outcomes, details=None: observed.append(outcomes) or "pending")
    settle_builder_predictions(
        scores={}, now=datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert observed == [["pending"]]


def test_missing_published_score_does_not_become_an_age_based_void(monkeypatch):
    from types import SimpleNamespace
    slip = SimpleNamespace(id=12, date="2026-09-01", picks=json.dumps([{
        "home_team": "Alpha", "away_team": "Beta", "market": "over_1_5",
        "commence_time": "2026-09-01T18:00:00Z",
    }]))
    monkeypatch.setattr("leagues.picks_db.pending_slips", lambda today: [slip])
    monkeypatch.setattr("leagues.results_checker._collect_espn_scores_ranged",
                        lambda start, end, slugs=None: {})
    observed = []
    monkeypatch.setattr("leagues.picks_db.settle_slip",
                        lambda slip_id, outcomes, details=None: observed.append(outcomes) or "pending")
    settle_published_slips()
    assert observed == [["pending"]]


def test_published_slip_reconciliation_is_read_only_and_reports_conflicts(monkeypatch):
    """Historical review must never become an accidental settlement backfill."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from leagues import results_checker
    from leagues.picks_db import PublishedSlip

    engine = create_engine("sqlite:///:memory:")
    PublishedSlip.__table__.create(engine)
    session = sessionmaker(bind=engine)
    original_void = [{
        "home_team": "Alpha", "away_team": "Beta", "market": "home_win",
        "commence_time": "2026-09-15T18:00:00Z", "status": "void",
    }]
    original_loss = [{
        "home_team": "Gamma", "away_team": "Delta", "market": "over_1_5",
        "commence_time": "2026-09-16T18:00:00Z", "status": "lost", "odds": 1.5,
    }]
    original_missing = [{
        "home_team": "Missing", "away_team": "Result", "market": "over_1_5",
        "commence_time": "2026-09-17T18:00:00Z", "status": "pending",
    }]
    with session() as db:
        db.add_all([
            PublishedSlip(date="2026-09-15", category="banker",
                          picks=json.dumps(original_void), total_odds=1.4,
                          presentation="accumulator", status="void"),
            PublishedSlip(date="2026-09-16", category="2_odds",
                          picks=json.dumps(original_loss), total_odds=1.5,
                          presentation="accumulator", status="lost"),
            PublishedSlip(date="2026-09-17", category="5_odds",
                          picks=json.dumps(original_missing), total_odds=1.6,
                          presentation="accumulator", status="pending"),
        ])
        db.commit()

    monkeypatch.setattr("database.SessionLocal", session)
    monkeypatch.setattr(results_checker, "_collect_scores_for_picks", lambda picks: ({
        "alpha|beta|2026-09-15": {
            "home_score": 2, "away_score": 0, "provider": "espn",
            "provider_event_id": "espn-alpha", "match_status": "STATUS_FINAL",
        },
        "gamma|delta|2026-09-16": {
            "home_score": 1, "away_score": 1, "provider": "api-football",
            "provider_event_id": "api-gamma", "match_status": "FT",
        },
    }, "espn+api-football"))

    writes = []

    def observe_write(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe_write)
    try:
        report = results_checker.reconcile_published_slips(
            start_date="2026-09-15", end_date="2026-09-24")
    finally:
        event.remove(engine, "before_cursor_execute", observe_write)

    assert report["dry_run"] is True
    assert report["score_source"] == "espn+api-football"
    assert report["slips_scanned"] == 3
    assert report["legs_scanned"] == 3
    assert writes == []
    assert report["slips"][0]["proposed_status"] == "won"
    assert report["slips"][0]["legs"][0]["score_evidence"]["provider"] == "espn"
    assert report["likely_historical_false_voids"]
    assert report["likely_incorrect_losses"]
    assert report["unresolved_legs"][0]["unresolved_reason"] == "FINAL_SCORE_UNVERIFIED"
    with session() as db:
        rows = db.query(PublishedSlip).order_by(PublishedSlip.id).all()
        assert [row.status for row in rows] == ["void", "lost", "pending"]
        assert [json.loads(row.picks) for row in rows] == [
            original_void, original_loss, original_missing,
        ]


def test_published_slip_reconciliation_rejects_apply_mode():
    from leagues.results_checker import reconcile_published_slips
    with pytest.raises(ValueError, match="strictly read-only"):
        reconcile_published_slips(dry_run=False)


def test_chain_sync_never_generates_predictions(monkeypatch):
    from leagues.results_checker import _sync_chain_to_db
    observed = []
    monkeypatch.setattr("leagues.daily_feed.build_daily_accumulators",
                        lambda **kwargs: observed.append(kwargs) or None)
    _sync_chain_to_db()
    assert observed == [{"force": False, "allow_generation": False}]


def test_result_provider_key_accepts_deployment_variable(monkeypatch):
    from leagues.results_checker import _get_apifootball_key
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    monkeypatch.delenv("APIFOOTBALL_API_KEY", raising=False)
    monkeypatch.setenv("API_FOOTBALL_API_KEY", "test-key")
    assert _get_apifootball_key() == "test-key"


def test_unknown_market_is_not_invented_as_a_void():
    assert _evaluate_pick({"market": "unsupported_market"}, 2, 1) == "pending"


def test_result_collector_uses_monthly_espn_contract(monkeypatch):
    from leagues import results_checker
    monkeypatch.setattr(results_checker, "ESPN_LEAGUE_SLUGS", {"league": "test.1"})
    requests_seen = []

    class Response:
        status_code = 200

        def json(self):
            return {"events": [{
                "id": "espn-1", "date": "2026-09-22T19:00:00Z",
                "competitions": [{
                    "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
                    "competitors": [
                        {"homeAway": "home", "score": "2", "team": {"displayName": "Alpha"}},
                        {"homeAway": "away", "score": "1", "team": {"displayName": "Beta"}},
                    ],
                }],
            }]}

    def get(url, params, timeout):
        requests_seen.append(params["dates"])
        return Response()

    monkeypatch.setattr(results_checker.requests, "get", get)
    scores = results_checker._collect_espn_scores_ranged(
        "2026-09-22", "2026-09-22")
    assert requests_seen == ["202609"]
    assert scores["alpha|beta|2026-09-22"]["provider_event_id"] == "espn-1"
    assert scores["alpha|beta|2026-09-22"]["home_score"] == 2


def test_result_name_normalization_keeps_distinct_squads():
    from leagues.results_checker import _normalize_name
    assert _normalize_name("Brøndby F.C.") == _normalize_name("Brondby FC")
    assert _normalize_name("Alpha FC U19") != _normalize_name("Alpha FC")
    assert _normalize_name("Alpha FC Women") != _normalize_name("Alpha FC")
    assert _normalize_name("Alpha FC II") != _normalize_name("Alpha FC")


def test_ambiguous_same_day_result_cannot_settle():
    from leagues.results_checker import _lookup_settlement_score, _settlement_detail
    scores = {"alpha|beta|2026-09-22": {"ambiguous": True}}
    assert _lookup_score(scores, "Alpha", "Beta", "2026-09-22") is None
    match = _lookup_settlement_score(scores, "Alpha", "Beta", "2026-09-22")
    assert _settlement_detail({"market": "over_1_5"}, match) == (
        "pending", {"settlement_pending_reason": "AMBIGUOUS_FIXTURE"})


def test_bounded_rollover_backfill_reviews_before_writing(monkeypatch):
    import json
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from leagues import results_checker
    from leagues.rollover_db import RolloverDay

    date = datetime.now(timezone.utc).date().isoformat()
    engine = create_engine("sqlite:///:memory:")
    RolloverDay.__table__.create(engine)
    session = sessionmaker(bind=engine)
    original = [{"home_team": "Alpha", "away_team": "Beta",
                 "commence_time": f"{date}T00:00:00Z",
                 "market_key": "home_win", "status": "pending"}]
    with session() as db:
        db.add(RolloverDay(chain_start_date=date, day_number=1, date=date,
                           picks=json.dumps(original), combined_odds=2.0,
                           avg_confidence=.7, status="lost"))
        db.commit()
    monkeypatch.setattr("database.SessionLocal", session)
    monkeypatch.setattr(results_checker, "_collect_scores_for_picks",
                        lambda picks: ({f"alpha|beta|{date}": {
                            "home_score": 2, "away_score": 1,
                            "provider": "espn", "provider_event_id": "e-1"}}, "espn"))

    review = results_checker.backfill_leg_status(limit_days=1)
    assert review["dry_run"] is True
    assert review["legs_filled"] == 1
    with session() as db:
        assert json.loads(db.query(RolloverDay).one().picks) == original

    applied = results_checker.backfill_leg_status(limit_days=1, dry_run=False)
    assert applied["legs_filled"] == 1
    with session() as db:
        row = db.query(RolloverDay).one()
        assert row.status == "lost"
        pick = json.loads(row.picks)[0]
        assert pick["status"] == "won"
        assert pick["settlement_evidence"]["provider_event_id"] == "e-1"


def test_collector_does_not_guess_between_same_day_rematches(monkeypatch):
    from leagues import results_checker
    monkeypatch.setattr(results_checker, "ESPN_LEAGUE_SLUGS", {"league": "test.1"})

    class Response:
        status_code = 200

        def json(self):
            def event(event_id, score):
                return {"id": event_id, "date": "2026-09-22T19:00:00Z",
                        "competitions": [{
                            "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
                            "competitors": [
                                {"homeAway": "home", "score": score,
                                 "team": {"displayName": "Alpha"}},
                                {"homeAway": "away", "score": "0",
                                 "team": {"displayName": "Beta"}},
                            ],
                        }]}
            return {"events": [event("one", "1"), event("two", "2")]}

    monkeypatch.setattr(results_checker.requests, "get", lambda *a, **kw: Response())
    scores = results_checker._collect_espn_scores_ranged(
        "2026-09-22", "2026-09-22")
    assert _lookup_score(scores, "Alpha", "Beta", "2026-09-22") is None


def test_partial_espn_coverage_uses_fallback_only_for_missing_pick(monkeypatch):
    from leagues import results_checker
    picks = [
        {"home_team": "Alpha", "away_team": "Beta", "commence_time": "2026-09-22T19:00:00Z",
         "sport_key": "soccer_spain_segunda_division"},
        {"home_team": "Gamma", "away_team": "Delta", "commence_time": "2026-09-22T20:00:00Z",
         "sport_key": "soccer_spain_segunda_division"},
    ]
    monkeypatch.setattr(results_checker, "_collect_espn_scores_ranged",
                        lambda start, end, slugs: {
                            "alpha|beta|2026-09-22": {"home_score": 2, "away_score": 0}})
    requested = []
    monkeypatch.setattr(results_checker, "_get_apifootball_key", lambda: "configured")
    monkeypatch.setattr(results_checker, "_get_odds_api_key", lambda: "")
    monkeypatch.setattr(results_checker, "_collect_apifootball_scores",
                        lambda keys, start, end: requested.append(keys) or {
                            "gamma|delta|2026-09-22": {"home_score": 1, "away_score": 1}})
    scores, source = results_checker._collect_scores_for_picks(picks)
    assert requested == [["soccer_spain_segunda_division"]]
    assert source == "espn+api-football"
    assert _lookup_score(scores, "Alpha", "Beta", "2026-09-22")["home_score"] == 2
    assert _lookup_score(scores, "Gamma", "Delta", "2026-09-22")["home_score"] == 1


def test_ready_rollover_day_settles_without_waiting_for_another_day(monkeypatch):
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from leagues import results_checker
    from leagues.rollover_db import RolloverDay

    engine = create_engine("sqlite:///:memory:")
    RolloverDay.__table__.create(engine)
    session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    old_kickoff = (now - timedelta(hours=8)).isoformat()
    recent_kickoff = (now - timedelta(hours=1)).isoformat()
    old_date = old_kickoff[:10]
    with session() as db:
        db.add_all([
            RolloverDay(chain_start_date=old_date, day_number=1, date=old_date,
                        picks=json.dumps([{
                            "home_team": "Alpha", "away_team": "Beta",
                            "commence_time": old_kickoff, "market_key": "home_win",
                            "status": "pending"}]), combined_odds=2.0,
                        avg_confidence=.7, status="pending"),
            RolloverDay(chain_start_date=old_date, day_number=2,
                        date=recent_kickoff[:10], picks=json.dumps([{
                            "home_team": "Gamma", "away_team": "Delta",
                            "commence_time": recent_kickoff, "market_key": "home_win",
                            "status": "pending"}]), combined_odds=2.0,
                        avg_confidence=.7, status="pending"),
        ])
        db.commit()
    monkeypatch.setattr("database.SessionLocal", session)
    monkeypatch.setattr(results_checker, "_sync_chain_to_db", lambda: None)
    monkeypatch.setattr(results_checker, "_collect_finished_scores",
                        lambda rows, has_club_picks: ({
                            f"alpha|beta|{old_date}": {
                                "home_score": 2, "away_score": 1,
                                "provider": "espn", "provider_event_id": "event-1"}},
                            "espn"))
    summary = results_checker.check_all_pending()
    assert summary["marked_won"] == 1
    assert summary["still_pending"] == 1
    with session() as db:
        rows = db.query(RolloverDay).order_by(RolloverDay.day_number).all()
        assert [row.status for row in rows] == ["won", "pending"]
        settled_pick = json.loads(rows[0].picks)[0]
        assert settled_pick["settlement_evidence"]["provider_event_id"] == "event-1"
