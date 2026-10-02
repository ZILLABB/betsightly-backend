"""Phase 9 odds evidence is immutable, exact and never a live-policy input."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from leagues import odds_history as history

UTC = timezone.utc
KICKOFF = datetime(2026, 10, 3, 18, tzinfo=UTC)
ENTRY_AT = KICKOFF - timedelta(hours=5)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'odds.db'}")
    history.metadata.create_all(engine)
    monkeypatch.setattr(history, "engine", engine)
    return engine


def observation(*, at=None, price=2.0, market="over_1_5", fixture="espn:m1",
                event="sporty-1", snapshot="s1", **overrides):
    return {"observed_at": at or ENTRY_AT + timedelta(hours=1),
            "provider": "sportybet", "provider_snapshot_id": snapshot,
            "canonical_fixture_id": fixture, "provider_event_id": event,
            "kickoff_utc": KICKOFF, "market": market, "selection": market,
            "bookmaker": "SportyBet", "decimal_odds": price,
            "bookable": True, "real_odds": True, **overrides}


def game(*, market="over_1_5", match="m1", odds=2.2, real=True):
    return {"match_id": match, "market": market, "kickoff": KICKOFF.isoformat(),
            "odds": odds, "odds_are_real": real,
            "sportybet_event_id": "sporty-1", "league_slug": "eng.1"}


def entry(**overrides):
    return {"canonical_fixture_id": "espn:m1", "provider_event_id": "sporty-1",
            "market": "over_1_5", "selection": "over_1_5",
            "kickoff_utc": KICKOFF, "selected_at": ENTRY_AT,
            "entry_odds": 2.2, "entry_source": "real_attached_provider_quote",
            **overrides}


def test_schema_and_append_only_idempotency(db):
    first = history.ingest_observations([observation()])
    again = history.ingest_observations([observation(price=9.0)])
    assert first["inserted"] == 1 and again["existing"] == 1
    with db.connect() as conn:
        rows = conn.execute(select(history.observations)).mappings().all()
    assert len(rows) == 1 and rows[0]["decimal_odds"] == 2.0


def test_multiple_snapshots_and_exact_closing_selection(db):
    history.ingest_observations([
        observation(snapshot="s1", price=2.0),
        observation(snapshot="s2", price=1.8, at=KICKOFF - timedelta(minutes=2)),
        observation(snapshot="s3", price=1.1, at=KICKOFF + timedelta(minutes=1)),
        observation(snapshot="s4", price=4.0, market="under_3_5"),
        observation(snapshot="s5", price=4.0, fixture="espn:other", event="other"),
    ])
    with db.connect() as conn:
        quotes = [dict(row) for row in conn.execute(select(history.observations)).mappings()]
    out = history.evaluate_entry(entry(), quotes, now=KICKOFF)
    assert out["status"] == "complete"
    assert out["closing_odds"] == 1.8
    assert out["entry_implied_probability"] == pytest.approx(1 / 2.2)
    assert out["closing_implied_probability"] == pytest.approx(1 / 1.8)
    assert out["price_clv"] == pytest.approx(2.2 / 1.8 - 1)
    assert out["probability_clv"] == pytest.approx(1 / 1.8 - 1 / 2.2)


def test_never_closes_before_window_or_from_after_kickoff():
    quote = observation(at=KICKOFF + timedelta(seconds=1))
    assert history.evaluate_entry(entry(), [quote], now=KICKOFF)["status"] == "unavailable"
    quote = observation(at=KICKOFF - timedelta(minutes=2))
    assert history.evaluate_entry(entry(), [quote], now=ENTRY_AT)["status"] == "pending"


def test_fixture_market_selection_and_kickoff_must_match():
    bad = [observation(fixture="espn:other", event="other"),
           observation(market="under_3_5"),
           observation(kickoff_utc=KICKOFF + timedelta(days=7))]
    assert history.evaluate_entry(entry(), bad, now=KICKOFF)["status"] == "unavailable"


def test_other_provider_event_id_collision_cannot_close_sportybet_entry():
    coincidental = observation(fixture="oddsapi:unrelated", event="sporty-1",
                               provider="the_odds_api")
    assert history.evaluate_entry(entry(), [coincidental], now=KICKOFF)["status"] == "unavailable"


def test_negative_clv():
    result = history.evaluate_entry(entry(), [observation(price=2.5)], now=KICKOFF)
    assert result["price_clv"] < 0 and result["probability_clv"] < 0


def test_rejects_model_prices_and_late_quotes_but_keeps_nonbookable_evidence(db):
    result = history.ingest_observations([
        observation(real_odds=False), observation(bookable=False),
        observation(at=KICKOFF), observation(price=float("nan")),
    ])
    assert result == {"inserted": 1, "existing": 0, "rejected": 3}
    with db.connect() as conn:
        quote = dict(conn.execute(select(history.observations)).mappings().one())
    assert quote["bookable"] is False
    assert history.evaluate_entry(entry(), [quote], now=KICKOFF)["status"] == "unavailable"


def test_builder_and_published_entries_link_without_estimates(db):
    games = [game(), game(market="under_3_5", match="m2", real=False)]
    builder = history.record_selection_entries("builder", "fingerprint", games,
                                               selected_at=ENTRY_AT, mode="game_count")
    daily = history.record_selection_entries("published", "42", [game()],
                                             selected_at=ENTRY_AT, mode="over_1_5")
    assert builder["inserted"] == daily["inserted"] == 1
    assert builder["skipped"] == 1
    assert history.record_selection_entries("builder", "fingerprint", games,
                                            selected_at=ENTRY_AT)["existing"] == 1
    with db.connect() as conn:
        rows = conn.execute(select(history.entries)).mappings().all()
    assert {r["source_kind"] for r in rows} == {"builder", "published"}


def test_validated_booking_precedence_does_not_claim_individual_readback(db):
    selected = {**game(), "sportybet_odds": 2.15,
                "sportybet_availability": {"sportybet_odds": 2.15,
                                           "sportybet_available": True}}
    booking = {"status": "active", "booking_status": "FULL",
               "readback_validation": "PASSED"}
    history.record_selection_entries("builder", "f", [selected],
                                     selected_at=ENTRY_AT, booking=booking)
    with db.connect() as conn:
        row = conn.execute(select(history.entries)).mappings().one()
    assert row["entry_odds"] == 2.15
    assert row["entry_source"] == "validated_booking_board_quote"


def test_report_counts_and_market_breakdown(db, monkeypatch):
    history.record_selection_entries("builder", "one", [game()], selected_at=ENTRY_AT)
    history.record_selection_entries("published", "two", [game(market="under_3_5")],
                                     selected_at=ENTRY_AT)
    history.ingest_observations([observation(price=1.8)])
    rows = history.selection_report(now=KICKOFF + timedelta(minutes=1))
    report = history.aggregate_report(rows)
    assert report["selection_count"] == 2
    assert report["evaluated_count"] == 1
    assert report["unavailable_count"] == 1
    assert report["by_market"]["over_1_5"]["evaluated_count"] == 1
    assert report["by_market"]["under_3_5"]["unavailable_count"] == 1
    assert report["by_provider"]["sportybet"]["evaluated_count"] == 1


def test_capture_reuses_already_fetched_board_without_provider_call(db, monkeypatch):
    from leagues import sportybet
    monkeypatch.setattr(sportybet, "fetch_board", lambda *a, **k: pytest.fail("network"))
    fixture = {"match_id": "m1", "commence_time": KICKOFF.isoformat(),
               "league_slug": "eng.1", "odds": {
                   "sportybet_event_id": "sporty-1", "over_1_5": 2.0}}
    board = {"__meta__": {"snapshot_id": "snap", "fetched_at": ENTRY_AT.timestamp()},
             "home|away": {"event_id": "sporty-1", "prices": {"over_1_5": 2.0}}}
    assert history.capture_sportybet_fixture_prices([fixture], board)["inserted"] == 1
    assert history.capture_sportybet_fixture_prices([fixture], board)["existing"] == 1


def test_entry_requires_real_price_and_exact_identity(db):
    invalid = {**game(), "match_id": None}
    result = history.record_selection_entries("builder", "x", [invalid],
                                              selected_at=ENTRY_AT)
    assert result["skipped"] == 1
    with pytest.raises(ValueError):
        history.record_selection_entries("unknown", "x", [], selected_at=ENTRY_AT)


def test_capture_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ODDS_HISTORY_CAPTURE_ENABLED", raising=False)
    assert history.capture_enabled() is False


def test_extra_closing_fetch_is_disabled_and_never_available_to_web(monkeypatch):
    from leagues import sportybet
    monkeypatch.setattr(sportybet, "fetch_board", lambda **kwargs: pytest.fail("network"))
    monkeypatch.delenv("ODDS_HISTORY_CLOSE_FETCH_ENABLED", raising=False)
    assert history.capture_closing_snapshot()["provider_calls"] == 0
    monkeypatch.setenv("ODDS_HISTORY_CLOSE_FETCH_ENABLED", "true")
    monkeypatch.setenv("BETSIGHTLY_PROCESS_ROLE", "web")
    assert history.capture_closing_snapshot()["status"] == "wrong_process_role"


def test_clv_admin_routes_require_api_key():
    from leagues.api import router
    from utils.security import require_api_key
    routes = {route.path: route for route in router.routes}
    for path in ("/clv/status", "/clv/report"):
        assert "GET" in routes[path].methods
        assert any(item.dependency is require_api_key
                   for item in routes[path].dependencies)


def test_existing_odds_api_fetch_is_archived_without_claiming_bookability(db):
    event = {"id": "ev-1", "home_team": "Home", "away_team": "Away",
             "commence_time": KICKOFF.isoformat(), "bookmakers": [{
                 "key": "book1", "title": "Book One",
                 "last_update": ENTRY_AT.isoformat(), "markets": [{
                     "key": "h2h", "outcomes": [
                         {"name": "Home", "price": 1.9},
                         {"name": "Draw", "price": 3.4},
                         {"name": "Away", "price": 4.2}]}]}]}
    result = history.capture_odds_api_events([event], "soccer_epl")
    assert result["inserted"] == 3
    assert history.capture_odds_api_events([event], "soccer_epl")["existing"] == 3
    with db.connect() as conn:
        rows = conn.execute(select(history.observations)).mappings().all()
    assert all(row["bookable"] is False for row in rows)


def test_observation_status_has_no_credentials(db):
    history.ingest_observations([observation()])
    status = history.status_report()
    assert status["observation_count"] == 1
    assert status["provider_counts"] == {"sportybet": 1}
    assert "token" not in str(status).lower()


def test_builder_archive_integrates_entry_capture_without_changing_result(db, monkeypatch):
    from leagues import builder_runs
    builder_runs.metadata.create_all(db, tables=[builder_runs.builder_predictions])
    monkeypatch.setattr(builder_runs, "engine", db)
    monkeypatch.setattr(builder_runs, "ensure_table", lambda: None)
    monkeypatch.setenv("ODDS_HISTORY_CAPTURE_ENABLED", "true")
    result = {"games": [game()], "odds": 2.2, "booking": {}}
    assert builder_runs.record_prediction(2.0, "7_days", result)
    with db.connect() as conn:
        row = conn.execute(select(history.entries)).mappings().one()
    assert row["source_kind"] == "builder"
    assert row["source_id"] == builder_runs._prediction_fingerprint(result)


def test_published_archive_integrates_without_rewriting_first_card(db, monkeypatch):
    from leagues import picks_db
    picks_db.PublishedSlip.__table__.create(db)
    monkeypatch.setattr(picks_db, "SessionLocal", sessionmaker(bind=db))
    monkeypatch.setattr(picks_db, "ensure_table", lambda: True)
    monkeypatch.setenv("ODDS_HISTORY_CAPTURE_ENABLED", "true")
    assert picks_db.archive_slip("2026-10-02", "over_1_5", [game()], 2.2, 0.7)
    assert picks_db.archive_slip("2026-10-02", "over_1_5", [game(odds=9.0)], 9.0, 0.7)
    with db.connect() as conn:
        row = conn.execute(select(history.entries)).mappings().one()
        slip = conn.execute(select(picks_db.PublishedSlip.__table__)).mappings().one()
    assert row["source_kind"] == "published" and row["source_id"] == str(slip["id"])
    assert row["entry_odds"] == 2.2


@pytest.mark.parametrize("previous_head", [False, True])
def test_real_migration_fresh_and_previous_schema_are_additive(tmp_path, monkeypatch,
                                                               previous_head):
    from alembic import command
    from alembic.config import Config
    import database

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr(database, "DATABASE_URL", url)
    config = Config("alembic.ini")
    if previous_head:
        command.upgrade(config, "add_prepared_board_cache")
        original = create_engine(url)
        with original.begin() as conn:
            conn.execute(text("CREATE TABLE phase9_existing_record (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO phase9_existing_record VALUES (17)"))
    command.upgrade(config, "head")
    migrated = create_engine(url)
    names = set(inspect(migrated).get_table_names())
    assert {"odds_observations", "odds_selection_entries", "prepared_board_cache"} <= names
    if previous_head:
        with migrated.connect() as conn:
            assert conn.execute(text("SELECT id FROM phase9_existing_record")).scalar() == 17
    monkeypatch.setattr(history, "engine", migrated)
    assert history.ingest_observations([observation()])["inserted"] == 1
    with pytest.raises(IntegrityError):
        with migrated.begin() as conn:
            conn.execute(history.observations.update().values(decimal_odds=9.0))


def test_backfill_is_bounded_read_only_by_default_and_resumable(db):
    from leagues import builder_runs, picks_db
    builder_runs.builder_predictions.create(db)
    picks_db.PublishedSlip.__table__.create(db)
    with db.begin() as conn:
        conn.execute(picks_db.PublishedSlip.__table__.insert().values(
            date="2026-10-03", category="over_1_5", picks=json.dumps([game()]),
            total_odds=2.2, created_at=ENTRY_AT.replace(tzinfo=None)))
    start = ENTRY_AT - timedelta(hours=1)
    end = KICKOFF + timedelta(hours=1)
    preview = history.backfill_archive_entries(start, end)
    assert preview["planned_entries"] == 1
    with db.connect() as conn:
        assert conn.execute(select(history.entries)).first() is None
    applied = history.backfill_archive_entries(start, end, dry_run=False)
    assert applied["inserted_entries"] == 1
    assert history.backfill_archive_entries(start, end, dry_run=False)["inserted_entries"] == 0
    with pytest.raises(ValueError):
        history.backfill_archive_entries(start, end + timedelta(days=40))
