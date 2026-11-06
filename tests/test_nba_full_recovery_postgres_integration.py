"""Real PostgreSQL full-V2 restore integration test; synthetic NBA data only.

Run with NBA_DISPOSABLE_POSTGRES_TEST_URL pointing to an EMPTY scratch
Postgres database. Never use active Supabase/Render credentials here.
"""
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from basketball import research_full_recovery as full
from basketball import research_full_recovery_postgres as pg
from basketball.research_coldstart import _json
from basketball.research_market_store import NBAMarketObservation
from basketball.research_ops_health import NBAPrivateJobRun, _session_tables
from tests.test_basketball_ops_health import prepare


@pytest.mark.skipif(not os.getenv("NBA_DISPOSABLE_POSTGRES_TEST_URL"),
                    reason="Separate disposable PostgreSQL required")
def test_actual_empty_postgres_restores_complete_v2_and_rejects_overwrite(tmp_path, monkeypatch):
    target = os.environ["NBA_DISPOSABLE_POSTGRES_TEST_URL"]
    assert "localhost" in target or "127.0.0.1" in target
    engine = create_engine(target)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS nba_research")
            assert inspect(conn).get_table_names(schema="nba_research") == []
    finally:
        engine.dispose()

    _, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        _session_tables(db)
        receipt = {"source":"synthetic_nba_coverage",
                   "observed_at":"2026-10-28T07:45:00+00:00",
                   "fixtures":[],"research_only":True}
        import hashlib
        receipt["digest"] = hashlib.sha256(_json(receipt).encode()).hexdigest()
        db.add(NBAMarketObservation(
            digest=receipt["digest"],payload_json=_json(receipt),
            recorded_at=datetime(2026,10,28,7,45)))
        db.add(NBAPrivateJobRun(
            kind="settlement",status="settled_and_verified",
            summary_json='{"new_finals":4,"outcome":"settled_and_verified"}',
            recorded_at=datetime(2026,10,28,7,47)))
        db.commit()
        backup = full.build_full_recovery(db=db)
        assert backup["portable_backup_v1"]["market_receipt_count"] == 1
        assert backup["job_receipt_count"] == 1

    kwargs = {
        "active_primary_url":"postgresql://readonly:dummy@original-supabase.invalid/prod",
        "original_render_url":"postgresql://readonly:dummy@original-render.invalid/nba",
    }
    report = pg.restore_full_v2_empty_postgres(backup,target,**kwargs)
    assert report["status"] == "disposable_full_postgres_restore_verified"
    assert report["market_receipt_count"] == 1
    assert report["job_receipt_count"] == 1
    assert report["source_unchanged"] is True
    assert report["production_switch_performed"] is False

    readback = create_engine(target)
    try:
        with readback.connect() as conn:
            from sqlalchemy import text
            assert conn.execute(text(
                "SELECT count(*) FROM nba_research.nba_private_research_snapshots")).scalar()==1
            assert conn.execute(text(
                "SELECT count(*) FROM nba_research.nba_private_market_observations")).scalar()==1
            assert conn.execute(text(
                "SELECT count(*) FROM nba_research.nba_private_job_runs")).scalar()==1
            assert conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name LIKE 'nba_private_%'")).scalar()==0
    finally:
        readback.dispose()

    with pytest.raises(ValueError, match="TARGET_NOT_EMPTY"):
        pg.restore_full_v2_empty_postgres(backup,target,**kwargs)
