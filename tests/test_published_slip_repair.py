"""Safety tests for the fixed-scope September published-slip repair."""

import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from leagues import published_slip_repair as repair
from leagues.picks_db import PublishedSlip


@pytest.fixture
def repair_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    PublishedSlip.__table__.create(engine)
    session = sessionmaker(bind=engine)
    rows = [
        PublishedSlip(
            date="2026-09-15", category="banker", total_odds=1.4,
            presentation="accumulator", status="void", picks=json.dumps([{
                "home_team": "Alpha", "away_team": "Beta", "market": "home_win",
                "commence_time": "2026-09-15T18:00:00Z", "status": "void",
            }]),
        ),
        PublishedSlip(
            date="2026-09-16", category="2_odds", total_odds=1.5,
            presentation="accumulator", status="lost", picks=json.dumps([{
                "home_team": "Gamma", "away_team": "Delta", "market": "over_1_5",
                "commence_time": "2026-09-16T18:00:00Z", "status": "lost", "odds": 1.5,
            }]),
        ),
        PublishedSlip(
            date="2026-09-17", category="5_odds", total_odds=1.6,
            presentation="accumulator", status="void", picks=json.dumps([{
                "home_team": "Missing", "away_team": "Result", "market": "over_1_5",
                "commence_time": "2026-09-17T18:00:00Z", "status": "void",
            }]),
        ),
        PublishedSlip(
            date="2026-09-25", category="outside_scope", total_odds=2.0,
            presentation="accumulator", status="void", picks=json.dumps([{
                "home_team": "Outside", "away_team": "Scope", "market": "home_win",
                "commence_time": "2026-09-25T18:00:00Z", "status": "void",
            }]),
        ),
    ]
    with session() as db:
        db.add_all(rows)
        db.commit()
    monkeypatch.setattr("database.SessionLocal", session)
    monkeypatch.setattr("leagues.results_checker._collect_scores_for_picks", lambda picks: ({
        "alpha|beta|2026-09-15": {
            "home_score": 2, "away_score": 0, "provider": "espn",
            "provider_event_id": "alpha-1", "match_status": "STATUS_FINAL",
        },
        "gamma|delta|2026-09-16": {
            "home_score": 1, "away_score": 1, "provider": "api-football",
            "provider_event_id": "gamma-1", "match_status": "FT",
        },
    }, "espn+api-football"))
    return engine, session


def _statuses(session):
    with session() as db:
        return [(row.id, row.status, json.loads(row.picks or "[]"))
                for row in db.query(PublishedSlip).order_by(PublishedSlip.id).all()]


def test_dry_run_makes_zero_database_writes(repair_db):
    engine, _ = repair_db
    writes = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        result = repair.run_repair()
    finally:
        event.remove(engine, "before_cursor_execute", observe)

    assert result["dry_run"] is True
    assert result["rows_to_change"] == 3
    assert result["legs_to_change"] == 3
    assert writes == []


def test_apply_repairs_false_void_loss_and_leaves_unresolved_pending(repair_db, tmp_path):
    _, session = repair_db
    result = repair.run_repair(
        apply=True, confirmation=repair.CONFIRM_TOKEN, backup_dir=tmp_path,
    )

    assert result["rows_changed"] == 3
    assert result["legs_changed"] == 3
    assert result["evidence_source"] == "espn+api-football"
    assert (tmp_path / result["backup_file"].split("\\")[-1]).exists()
    with open(result["backup_file"], encoding="utf-8") as backup_file:
        backup = json.load(backup_file)
    assert [(row["date"], row["category"], row["status"])
            for row in backup["rows"]] == [
                ("2026-09-15", "banker", "void"),
                ("2026-09-16", "2_odds", "lost"),
                ("2026-09-17", "5_odds", "void"),
            ]
    original_pick = [{
        "home_team": "Alpha", "away_team": "Beta", "market": "home_win",
        "commence_time": "2026-09-15T18:00:00Z", "status": "void",
    }]
    assert backup["rows"][0]["picks"] == original_pick
    statuses = _statuses(session)
    assert [status for _, status, _ in statuses] == ["won", "won", "pending", "void"]
    assert statuses[0][2][0]["settlement_evidence"]["provider"] == "espn"
    assert statuses[1][2][0]["settlement_evidence"]["provider"] == "api-football"
    assert statuses[2][2][0]["status"] == "pending"
    assert statuses[2][2][0]["settlement_pending_reason"] == "FINAL_SCORE_UNVERIFIED"
    # The 25th is deliberately outside the hard-coded incident window.
    assert statuses[3][2][0]["status"] == "void"


def test_precondition_mismatch_aborts_the_entire_apply(repair_db, tmp_path):
    _, session = repair_db
    plan = repair.build_repair_plan()
    before = _statuses(session)
    with session() as db:
        first = db.query(PublishedSlip).filter(PublishedSlip.id == plan["targets"][0]["slip_id"]).one()
        first.status = "won"
        db.commit()

    with pytest.raises(repair.RepairPreconditionError, match="changed after reconciliation"):
        repair.apply_repair_plan(
            plan, confirmation=repair.CONFIRM_TOKEN, backup_dir=tmp_path,
        )
    after = _statuses(session)
    # Only the deliberate concurrent mutation exists; no planned row was repaired.
    assert after[1:] == before[1:]


def test_transaction_failure_rolls_back_all_target_rows(repair_db, monkeypatch, tmp_path):
    _, session = repair_db
    plan = repair.build_repair_plan()
    before = _statuses(session)
    original_apply = repair._apply_target
    calls = []

    def fail_on_second(row, target):
        calls.append(row.id)
        changed = original_apply(row, target)
        if len(calls) == 2:
            raise RuntimeError("simulated transaction failure")
        return changed

    monkeypatch.setattr(repair, "_apply_target", fail_on_second)
    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        repair.apply_repair_plan(
            plan, confirmation=repair.CONFIRM_TOKEN, backup_dir=tmp_path,
        )
    assert _statuses(session) == before


def test_apply_requires_the_deliberate_confirmation_token(repair_db, tmp_path):
    plan = repair.build_repair_plan()
    with pytest.raises(repair.RepairPreconditionError, match="confirmation"):
        repair.apply_repair_plan(plan, confirmation="wrong", backup_dir=tmp_path)
