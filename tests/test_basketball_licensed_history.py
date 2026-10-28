"""Rights-gated six-league historical importer — synthetic data only."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from basketball.research_licensed_history import (
    import_licensed_history, validate_history_batch, history_readiness,
)
from basketball.research_multileague_release_gates import CANDIDATE_LEAGUES

START="2025-11-03T19:00:00+00:00"

def synthetic_game(game_id="synthetic-1",home_score=93):
    return {
        "provider_event_id":game_id,
        "tipoff_utc":START,
        "home_team_id":"fiction-home",
        "away_team_id":"fiction-away",
        "status":"final","home_score":home_score,"away_score":84,
    }

def test_six_league_schema_allows_synthetic_final_only():
    for league in CANDIDATE_LEAGUES:
        rows,digest=validate_history_batch(
            league,"test_licensed_provider","2025-26",[synthetic_game()])
        assert len(rows)==1
        assert len(digest)==64
        assert rows[0]["status"]=="final"
        assert len(rows[0]["row_sha256"])==64
    with pytest.raises(ValueError,match="LEAGUE_OR_PROVIDER"):
        validate_history_batch("nba","test_licensed_provider","2025-26",
                               [synthetic_game()])

@pytest.mark.parametrize("change,error",[
    ({"status":"scheduled","home_score":None,"away_score":None},"NONFINAL"),
    ({"status":"canceled","home_score":None,"away_score":None},"NONFINAL"),
    ({"home_score":84},"FINAL"),
    ({"home_score":True},"FINAL"),
    ({"tipoff_utc":"2025-11-03T19:00:00"},"TIPOFF"),
    ({"home_team_id":"fiction-away"},"DUPLICATE"),
    ({"unexpected_field":True},"ROW_SCHEMA"),
])
def test_forged_or_immature_history_is_rejected(change,error):
    with pytest.raises(ValueError,match=error):
        validate_history_batch("wnba","test_licensed_provider","2025-26",
                               [{**synthetic_game(),**change}])

def test_duplicate_or_overlong_history_is_rejected():
    with pytest.raises(ValueError,match="DUPLICATE"):
        validate_history_batch("wnba","test_licensed_provider","2025-26",
                               [synthetic_game(),synthetic_game()])
    with pytest.raises(ValueError,match="BATCH_COUNT"):
        validate_history_batch("wnba","test_licensed_provider","2025-26",
                               [synthetic_game(str(i)) for i in range(1001)])

@pytest.fixture(scope="module")
def postgres():
    url=os.getenv("BASKETBALL_TEST_PG_URL")
    if not url:
        pytest.skip("Disposable Postgres only; never target live Supabase.")
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS nba_research")
        source=(Path(__file__).parents[1]/
                "sql/nba_private_licensed_history_20261028.sql").read_text()
        for stmt in source.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    try:
        yield engine,sessionmaker(bind=engine)
    finally:
        engine.dispose()

def _grant(conn,league, *, storage=False,training=False,betting=False,
           expires=True,provider="test_licensed_provider"):
    now=datetime.now(timezone.utc)
    result=conn.execute(text("""
        INSERT INTO nba_research.basketball_data_rights
        (league,provider,status,evidence_sha256,licensed_storage,
        licensed_training,licensed_betting_use,approved_at,expires_at)
        VALUES (:league,:provider,'verified',:digest,:storage,:training,
                :betting,:approved,:expires) RETURNING id
    """),{
        "league":league,"provider":provider,
        "digest":("a" if league=="wnba" else "b")*64,
        "storage":storage,"training":training,"betting":betting,
        "approved":now-timedelta(days=1),
        "expires":now+timedelta(days=365) if expires else now-timedelta(hours=1)
    }).scalar_one()
    return result

def test_actual_postgres_rights_and_immutable_readback(postgres):
    engine,factory=postgres
    with pytest.raises(ValueError,match="RIGHTS_NOT_VERIFIED"):
        import_licensed_history("wnba","test_licensed_provider","2025-26",
                                [synthetic_game()],session_factory=factory)
    with engine.begin() as conn:
        rights_id=_grant(conn,"wnba")  # all three permission flags false
    with pytest.raises(ValueError,match="RIGHTS_NOT_VERIFIED"):
        import_licensed_history("wnba","test_licensed_provider","2025-26",
                                [synthetic_game()],session_factory=factory)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE nba_research.basketball_data_rights
            SET licensed_storage=true,licensed_training=true,
                licensed_betting_use=true WHERE id=:id
        """),{"id":rights_id})
    result=import_licensed_history("wnba","test_licensed_provider","2025-26",
                                   [synthetic_game()],session_factory=factory)
    assert result["status"]=="licensed_history_saved"
    assert result["count"]==1 and result["public_publishing_enabled"] is False
    again=import_licensed_history("wnba","test_licensed_provider","2025-26",
                                  [synthetic_game()],session_factory=factory)
    assert again["status"]=="already_imported"
    with pytest.raises(Exception):  # integrity: cannot rewrite final
        import_licensed_history("wnba","test_licensed_provider","2025-26",
                                [synthetic_game(home_score=94)],
                                session_factory=factory)
    with engine.begin() as conn:
        saved=conn.execute(text("""
            SELECT COUNT(*),MIN(home_score) FROM nba_research.basketball_licensed_games
            WHERE league='wnba'
        """)).one()
    assert tuple(saved)==(1,93)
    report=history_readiness(session_factory=factory)
    w=next(x for x in report["leagues"] if x["league"]=="wnba")
    assert w["active_commercial_data_grants"]==1
    assert w["imported_games"]==1
    assert w["complete_historical_seasons_verified"]==0
    assert w["approved_model"] is False

def test_postgres_expired_rights_and_league_isolation(postgres):
    engine,factory=postgres
    with engine.begin() as conn:
        _grant(conn,"eurocup",storage=True,training=True,betting=True,
               expires=False)
    with pytest.raises(ValueError,match="RIGHTS_NOT_VERIFIED"):
        import_licensed_history("eurocup","test_licensed_provider","2025-26",
                                [synthetic_game()],session_factory=factory)
    with engine.begin() as conn:
        _grant(conn,"ncaa_men",storage=True,training=True,betting=True)
    result=import_licensed_history("ncaa_men","test_licensed_provider","2025-26",
                                   [synthetic_game()],session_factory=factory)
    assert result["status"]=="licensed_history_saved"
    # Fixture identifier may repeat across distinct leagues; neither overwrites.
    with engine.begin() as conn:
        counts=conn.execute(text("""
            SELECT league,COUNT(*) n
            FROM nba_research.basketball_licensed_games GROUP BY league
            ORDER BY league
        """)).all()
        assert {row[0]:row[1] for row in counts}=={"ncaa_men":1,"wnba":1}
        rls=conn.execute(text("""
            SELECT relname,relrowsecurity FROM pg_class WHERE relnamespace=
            'nba_research'::regnamespace AND relname LIKE 'basketball_%'
        """)).all()
        assert len(rls)==3 and all(row[1] for row in rls)
        access=conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.role_table_grants
            WHERE table_schema='nba_research'
            AND table_name LIKE 'basketball_%'
            AND grantee IN ('anon','authenticated')
        """)).scalar_one()
        assert access==0
