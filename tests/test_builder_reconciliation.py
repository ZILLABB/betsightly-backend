"""Read-only incident reconciliation for immutable Builder predictions."""

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool

from leagues import builder_runs, builder_reconciliation


def _insert_prediction(conn, fingerprint, created_at, status, picks, *, target=2.0):
    conn.execute(builder_runs.builder_predictions.insert().values(
        selection_fingerprint=fingerprint,
        created_at=created_at,
        target_odds=target,
        horizon="week",
        generated_odds=2.4,
        leg_count=len(picks),
        picks=json.dumps(picks),
        final_status=status,
    ))


def test_builder_reconciliation_reports_proposals_without_writes(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    monkeypatch.setattr(builder_runs, "engine", engine)
    builder_runs.builder_predictions.create(engine)
    inside = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
    outside = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    with engine.begin() as conn:
        _insert_prediction(conn, "void-to-win", inside, "void", [{
            "home_team": "Alpha", "away_team": "Beta", "market": "home_win",
            "kickoff": "2026-09-15T18:00:00Z", "status": "void", "odds": 1.5,
        }])
        _insert_prediction(conn, "loss-to-win", inside, "lost", [{
            "home_team": "Gamma", "away_team": "Delta", "market": "over_1_5",
            "kickoff": "2026-09-16T18:00:00Z", "status": "lost", "odds": 1.6,
        }])
        _insert_prediction(conn, "void-to-pending", inside, "void", [{
            "home_team": "Missing", "away_team": "Result", "market": "over_1_5",
            "kickoff": "2026-09-17T18:00:00Z", "status": "void", "odds": 1.5,
        }])
        _insert_prediction(conn, "outside", outside, "void", [{
            "home_team": "Outside", "away_team": "Scope", "market": "home_win",
            "kickoff": "2026-09-25T18:00:00Z", "status": "void", "odds": 1.5,
        }])

    monkeypatch.setattr("leagues.results_checker._collect_scores_for_picks", lambda picks: ({
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

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        report = builder_reconciliation.reconcile_builder_predictions()
    finally:
        event.remove(engine, "before_cursor_execute", observe)

    assert writes == []
    assert report["dry_run"] is True
    assert report["predictions_scanned"] == 3
    assert report["legs_scanned"] == 3
    assert report["score_source"] == "espn+api-football"
    assert [item["proposed_final_status"] for item in report["predictions"]] == [
        "won", "won", "pending",
    ]
    first, second, third = report["predictions"]
    assert first["proposed_actual_settled_return"] == 1.5
    assert first["proposed_profit"] == .5
    assert first["proposed_all_win"] is True
    assert first["proposed_target_reached"] is False
    assert first["legs"][0]["score_evidence"]["provider_event_id"] == "espn-alpha"
    assert second["proposed_actual_settled_return"] == 1.6
    assert third["proposed_actual_settled_return"] is None
    assert third["legs"][0]["unresolved_reason"] == "FINAL_SCORE_UNVERIFIED"
    assert len(report["likely_false_builder_voids"]) >= 2
    assert report["likely_incorrect_builder_losses"]
    assert len(report["unresolved_builder_legs"]) == 1
    assert len(report["final_status_changes"]) == 3

    with engine.connect() as conn:
        rows = conn.execute(select(builder_runs.builder_predictions).order_by(
            builder_runs.builder_predictions.c.selection_fingerprint
        )).mappings().all()
    assert [(row["selection_fingerprint"], row["final_status"])
            for row in rows] == [
                ("loss-to-win", "lost"), ("outside", "void"),
                ("void-to-pending", "void"), ("void-to-win", "void"),
            ]
    assert json.loads(next(row for row in rows if row["selection_fingerprint"] == "void-to-win")["picks"])[0]["status"] == "void"
