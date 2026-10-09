"""Regression tests for guarded staging-only market-shadow settlement."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from scripts import settle_staging_market_shadow as settle

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
KICKOFF = NOW - timedelta(hours=8)


def fixture(market="over_1_5", **overrides):
    return {
        "observation_key": "one",
        "fixture_id": "fixture-A",
        "league_slug": "bra.1",
        "home_team": "Athletico-PR",
        "away_team": "Atlético-MG",
        "market": market,
        "kickoff": KICKOFF,
        "observed_at": KICKOFF - timedelta(hours=1),
        **overrides,
    }


def final(**overrides):
    return {
        "provider_event_id": "123",
        "league_slug": "bra.1",
        "home": settle._normalize("Athletico-PR"),
        "away": settle._normalize("Atlético-MG"),
        "kickoff": KICKOFF,
        "home_score": 2,
        "away_score": 1,
        "source": "espn:bra.1:123",
        **overrides,
    }


def indexed_final(*events):
    return {("bra.1", settle._normalize("Athletico-PR"),
             settle._normalize("Atlético-MG")): list(events)}


def test_exact_matching_requires_same_league_team_names_and_kickoff():
    assert settle._match_final(fixture(), indexed_final(final()))[1] == "VERIFIED"
    assert settle._match_final(
        fixture(league_slug="mex.2"), indexed_final(final())
    )[1] == "NO_EXACT_VERIFIED_FINAL"
    assert settle._match_final(
        fixture(kickoff=KICKOFF + timedelta(hours=2)), indexed_final(final())
    )[1] == "NO_EXACT_VERIFIED_FINAL"
    assert settle._match_final(fixture(), indexed_final(
        final(), final(provider_event_id="456")
    ))[1] == "AMBIGUOUS_FINAL"


def test_market_grading_and_void_preserve_90_minute_score():
    rows = [
        fixture(market="over_1_5"),
        fixture(market="under_2_5", observation_key="two"),
        fixture(market="dnb_home", observation_key="three"),
    ]
    updates, reasons, matches = settle.decisions_for_rows(rows, indexed_final(final()))
    assert (matches, reasons) == (1, {})
    assert [x["outcome"] for x in updates] == [1, 0, 1]
    draw, _, _ = settle.decisions_for_rows(
        [fixture(market="dnb_home")],
        indexed_final(final(home_score=1, away_score=1)),
    )
    assert draw[0]["status"] == "void" and draw[0]["outcome"] is None


def test_missing_ambiguous_and_unsupported_results_stay_pending():
    rows = [fixture(), fixture(market="made_up_market", observation_key="other")]
    updates, reasons, _ = settle.decisions_for_rows(rows, {})
    assert updates == []
    assert reasons == {"NO_EXACT_VERIFIED_FINAL": 2}
    updates, reasons, _ = settle.decisions_for_rows(
        rows, indexed_final(final())
    )
    assert len(updates) == 1
    assert reasons == {"UNSUPPORTED_MARKET": 1}


def test_no_write_without_separate_confirmation_even_with_database_credentials(
    monkeypatch,
):
    monkeypatch.delenv("BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError, match="Refusing write"):
        settle.require_write_authorization()
    monkeypatch.setenv(
        "BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE", settle.CONFIRMATION
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(RuntimeError, match="prohibited in GitHub"):
        settle.require_write_authorization()


def _sqlite_shadow():
    db = create_engine("sqlite:///:memory:")
    with db.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        conn.exec_driver_sql("""
            CREATE TABLE public.market_shadow_forecasts_v1 (
                observation_key TEXT PRIMARY KEY, fixture_id TEXT, market TEXT,
                league_slug TEXT, home_team TEXT, away_team TEXT,
                kickoff TIMESTAMP, observed_at TIMESTAMP,
                status TEXT, home_score INTEGER, away_score INTEGER,
                outcome INTEGER, settlement_source TEXT, settled_at TIMESTAMP
            )
        """)
        conn.execute(text("""
            INSERT INTO public.market_shadow_forecasts_v1
              (observation_key, fixture_id, market, league_slug, home_team,
               away_team, kickoff, observed_at, status)
            VALUES (:observation_key, :fixture_id, :market, :league_slug,
                    :home_team, :away_team, :kickoff, :observed_at, 'pending')
        """), fixture())
    return db


def test_reconcile_dry_run_then_write_is_idempotent(monkeypatch):
    db = _sqlite_shadow()
    monkeypatch.setattr(settle, "database_guard", lambda **kwargs:
                        "betsightly_db_staging")
    fetcher = lambda rows: (indexed_final(final()), {})
    preview = settle.reconcile(
        now=NOW, db_engine=db, fetcher=fetcher,
    )
    assert preview["status"] == "DRY_RUN_ONLY"
    assert preview["would_settle"] == 1
    assert preview["rows_updated"] == 0
    with db.connect() as conn:
        state = conn.execute(text(
            "SELECT status FROM public.market_shadow_forecasts_v1"
        )).scalar()
        assert state == "pending"
    written = settle.reconcile(
        write=True, now=NOW, db_engine=db, fetcher=fetcher,
    )
    assert written["rows_updated"] == 1
    again = settle.reconcile(
        write=True, now=NOW, db_engine=db, fetcher=fetcher,
    )
    assert again["rows_updated"] == 0
    with db.connect() as conn:
        state = conn.execute(text("""
            SELECT status, outcome, home_score, away_score, settlement_source
            FROM public.market_shadow_forecasts_v1
        """)).one()
    assert tuple(state) == ("settled", 1, 2, 1, "espn:bra.1:123")


def test_provider_event_must_be_completed_and_have_regulation_score(monkeypatch):
    from leagues import results_checker
    monkeypatch.setattr(results_checker, "regulation_score",
                        lambda comp: {"home_score": 1, "away_score": 0})
    event = {
        "id": "123", "date": KICKOFF.isoformat(),
        "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "Athletico-PR"}},
                {"homeAway": "away", "team": {"displayName": "Atlético-MG"}},
            ],
        }],
    }
    assert settle._event_final(event, "bra.1")["home_score"] == 1
    event["competitions"][0]["status"]["type"]["completed"] = False
    assert settle._event_final(event, "bra.1") is None
