"""Real PostgreSQL 18 four-table recovery using only fabricated games/grants."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import os
import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from basketball.research_coldstart import _json
from basketball.research_licensed_backup import (
    build_history_recovery, verify_history_recovery, SCOPES,
)
from basketball.research_licensed_backup_restore import restore_licensed_history_empty_postgres
from basketball.research_licensed_backup_ack import (
    verify_and_record_history_ack,
)
from basketball.research_licensed_history import validate_history_batch

ROOT=Path(__file__).resolve().parents[1]

def fake_history():
    row={
        "provider_event_id":"fake-001",
        "tipoff_utc":"2025-11-12T17:45:00+00:00",
        "home_team_id":"fake-east", "away_team_id":"fake-west",
        "status":"final","home_score":91,"away_score":88,
    }
    return validate_history_batch("wnba","synthetic_test_data","2025-26",[row])

@pytest.fixture(scope="module")
def pg():
    url=os.getenv("BASKETBALL_TEST_PG_URL")
    if not url:
        pytest.skip("No disposable PostgreSQL configured; never use live DB")
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE ROLE anon NOLOGIN")
        conn.exec_driver_sql("CREATE ROLE authenticated NOLOGIN")
        conn.exec_driver_sql("CREATE SCHEMA nba_research")
        for name in ("sql/nba_private_licensed_history_20261028.sql",
                     "sql/nba_private_licensed_backup_receipts_20261028.sql",
                     "sql/nba_private_six_league_source_probes_20261028.sql"):
            for sql in (ROOT/name).read_text().split(";"):
                if sql.strip():
                    conn.exec_driver_sql(sql)
        now=datetime(2026,10,27,14,tzinfo=timezone.utc)
        rights=conn.execute(text("""
            INSERT INTO nba_research.basketball_data_rights
            (league,provider,status,evidence_sha256,licensed_storage,
             licensed_training,licensed_betting_use,licensed_redistribution,
             approved_at,expires_at,created_at)
            VALUES ('wnba','synthetic_test_data','verified',:hash,
                    true,true,true,false,:at,:expiry,:at) RETURNING id
        """),{"hash":"a"*64,"at":now,"expiry":now+timedelta(days=80)}).scalar_one()
        rows,manifest=fake_history()
        imported=conn.execute(text("""
            INSERT INTO nba_research.basketball_licensed_imports
            (rights_id,league,provider,season_code,manifest_sha256,event_count)
            VALUES (:rights,'wnba','synthetic_test_data','2025-26',:manifest,1)
            RETURNING id
        """),{"rights":rights,"manifest":manifest}).scalar_one()
        record=rows[0]
        conn.execute(text("""
            INSERT INTO nba_research.basketball_licensed_games
            (import_id,league,provider,provider_event_id,season_code,tipoff_utc,
             home_team_id,away_team_id,status,home_score,away_score,row_sha256)
            VALUES (:import_id,'wnba','synthetic_test_data',:provider_event_id,'2025-26',
                    :tipoff_utc,:home_team_id,:away_team_id,'final',:home_score,
                    :away_score,:row_sha256)
        """),{**record,"import_id":imported})
        conn.execute(text("""
            INSERT INTO nba_research.nba_league_source_probes
            (league,provider,scope_key,recorded_at,http_status,events_observed,
             identity_complete,parsed_final_count,source_page_complete,
             commercial_use_cleared,source_probe_only)
            VALUES ('wnba','espn_site_candidate','20261028',:at,
                    200,2,2,2,false,false,true)
        """),{"at":now})
    try:
        yield engine,sessionmaker(bind=engine),url
    finally:
        engine.dispose()

def test_real_pg_export_hashes_and_tamper_rejection(pg):
    _,factory,_=pg
    envelope=build_history_recovery(session_factory=factory)
    result=verify_history_recovery(envelope)
    assert result["counts"]=={"rights":1,"imports":1,"games":1,"probes":1}
    assert len(envelope["tables_sha256"])==64
    assert "fake-east" in _json(envelope)
    broken=json.loads(_json(envelope))
    broken["tables"]["games"][0]["home_score"]=77
    with pytest.raises(ValueError,match="TABLE_HASH"):
        verify_history_recovery(broken)
    bad=json.loads(_json(envelope))
    bad["counts"]["rights"]=2
    with pytest.raises(ValueError,match="COUNT_MISMATCH"):
        verify_history_recovery(bad)

def test_real_pg_rejects_false_ack_and_records_verified_example(pg):
    _,factory,_=pg
    envelope=build_history_recovery(session_factory=factory)
    now=datetime.now(timezone.utc)
    receipt={
        "verified":True,"store":"private_vercel_blob_licensed_history_v1",
        "tables_sha256":envelope["tables_sha256"],
        "blob_sha256":"b"*64,
        "counts":envelope["counts"],
        "export_created_at":now.isoformat(),
    }
    with pytest.raises(ValueError,match="SOURCE_CHANGED"):
        verify_and_record_history_ack(
            {**receipt,"tables_sha256":"f"*64},
            session_factory=factory,now=now,exporter=lambda:envelope)
    with pytest.raises(ValueError,match="STALE"):
        verify_and_record_history_ack(
            {**receipt,"export_created_at":(now-timedelta(minutes=19)).isoformat()},
            session_factory=factory,now=now,exporter=lambda:envelope)
    outcome=verify_and_record_history_ack(
        receipt,session_factory=factory,now=now,exporter=lambda:envelope
    )
    assert outcome["status"]=="verified_licensed_history_private_blob_readback"

def test_disposable_pg_restores_every_table_and_blocks_second_restore(pg):
    engine,factory,url=pg
    envelope=build_history_recovery(session_factory=factory)
    from sqlalchemy.engine import make_url
    import psycopg2
    u=make_url(url)
    target=u.set(database="basketball_empty_restored")
    # Production source hosts are deliberately fictitious and distinct.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("CREATE DATABASE basketball_empty_restored"))
    remote=create_engine(target)
    with remote.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA nba_research")
        # These roles exist cluster-wide as created in source fixture.
    remote.dispose()
    restored=restore_licensed_history_empty_postgres(
        envelope,target.render_as_string(hide_password=False),
        active_primary_url="postgresql://primary.example.net/research",
        original_render_url="postgresql://render.example.net/research"
    )
    assert restored["counts"]=={"rights":1,"imports":1,"games":1,"probes":1}
    with pytest.raises(ValueError,match="TARGET_NOT_EMPTY"):
        restore_licensed_history_empty_postgres(
            envelope,target.render_as_string(hide_password=False),
            active_primary_url="postgresql://primary.example.net/research",
            original_render_url="postgresql://render.example.net/research"
        )
    with pytest.raises(ValueError):
        restore_licensed_history_empty_postgres(
            envelope,url,active_primary_url=url,original_render_url=url
        )
