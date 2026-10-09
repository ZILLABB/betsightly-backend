"""Staging-only bookmaker history never fabricates additional price captures."""
from copy import deepcopy
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from scripts import capture_staging_odds_history as capture

NOW = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)
FETCHED = NOW - timedelta(minutes=20)
KICKOFF = NOW + timedelta(hours=5)
SID = "0123456789abcdef"


def cache(*, prices=None):
    ts = FETCHED.timestamp()
    return {
        "fetched_at": ts,
        "metadata": {
            "snapshot_id": SID,
            "fetched_at": ts,
            "is_complete": True,
            "error": None,
        },
        "fixtures": {
            "home|away": [
                {
                    "event_id": "sr:match:123",
                    "home_team": "Home",
                    "away_team": "Away",
                    "kickoff_ms": int(KICKOFF.timestamp() * 1000),
                    "prices": prices if prices is not None else {
                        "home_win": 1.80,
                        "over_1_5": 1.26,
                    },
                },
            ],
        },
    }


def test_capture_preserves_original_provider_time_and_real_price_identity():
    rows, report = capture.rows_from_cache(cache(), now=NOW)
    assert len(rows) == 2
    assert report["eligible_fixtures"] == 1
    assert report["eligible_prices"] == 2
    assert report["source_captured_at"] == FETCHED.isoformat()
    assert report["network_requests_made"] is False
    assert report["clv_proven"] is False
    assert all(row["captured_at"] == FETCHED for row in rows)
    assert all(row["sportybet_event_id"] == "sr:match:123" for row in rows)
    assert {row["market"] for row in rows} == {"home_win", "over_1_5"}
    # Reruns must NOT label old odds with the new execution timestamp.
    rerun, _ = capture.rows_from_cache(cache(), now=NOW + timedelta(hours=1))
    assert rerun == rows


@pytest.mark.parametrize("problem", [
    "incomplete", "missing_snapshot", "stale", "future", "source_mismatch",
])
def test_fail_closed_for_uncertain_or_fake_snapshot_provenance(problem):
    data = cache()
    now = NOW
    if problem == "incomplete":
        data["metadata"]["is_complete"] = False
    elif problem == "missing_snapshot":
        data["metadata"]["snapshot_id"] = ""
    elif problem == "stale":
        now += timedelta(hours=7)
    elif problem == "future":
        data["metadata"]["fetched_at"] += 7200
        data["fetched_at"] += 7200
    elif problem == "source_mismatch":
        data["metadata"]["fetched_at"] += 400
    with pytest.raises(ValueError):
        capture.rows_from_cache(data, now=now)


def test_near_kickoff_and_invalid_prices_are_excluded():
    data = cache(prices={
        "over_1_5": 1.44,
        "under_2_5": float("nan"),
        "btts_yes": 1.0,
        "home_win": "not-a-price",
    })
    rows, report = capture.rows_from_cache(data, now=NOW)
    assert len(rows) == 1 and rows[0]["market"] == "over_1_5"
    assert report["skipped"]["bad_price"] == 3
    data["fixtures"]["home|away"][0]["kickoff_ms"] = int(
        (FETCHED + timedelta(minutes=9)).timestamp() * 1000
    )
    with pytest.raises(ValueError, match="No eligible"):
        capture.rows_from_cache(data, now=NOW)


def test_source_fixture_collision_cannot_overwrite_quote():
    data = cache()
    duplicate = deepcopy(data["fixtures"]["home|away"][0])
    duplicate["prices"]["home_win"] = 1.99
    data["fixtures"]["home|away"].append(duplicate)
    with pytest.raises(ValueError, match="Conflicting"):
        capture.rows_from_cache(data, now=NOW)


def test_event_id_cannot_merge_two_different_fixtures():
    data = cache()
    duplicate = deepcopy(data["fixtures"]["home|away"][0])
    duplicate["away_team"] = "Entirely Different Club"
    duplicate["prices"] = {"btts_yes": 1.70}
    data["fixtures"]["other|away"] = [duplicate]
    with pytest.raises(ValueError, match="multiple fixtures"):
        capture.rows_from_cache(data, now=NOW)


def test_same_event_id_and_fixture_can_merge_disjoint_active_markets():
    data = cache()
    duplicate = deepcopy(data["fixtures"]["home|away"][0])
    duplicate["prices"] = {"btts_yes": 1.65}
    data["fixtures"]["home|away"].append(duplicate)
    rows, report = capture.rows_from_cache(data, now=NOW)
    assert len(rows) == 3
    assert report["eligible_fixtures"] == 1


def test_conflicting_cache_metadata_does_not_create_history():
    data = cache()
    data["metadata"]["error"] = "page missing"
    with pytest.raises(ValueError, match="Incomplete"):
        capture.rows_from_cache(data, now=NOW)


def test_write_requires_separate_staging_confirmation_and_no_github_actions(
    monkeypatch,
):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE", raising=False)
    with pytest.raises(RuntimeError, match="confirmation"):
        capture.require_write_guard()
    monkeypatch.setenv("BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE", capture.CONFIRM)
    capture.require_write_guard()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(RuntimeError, match="GitHub Actions"):
        capture.require_write_guard()


def test_insert_sql_is_idempotent_and_cannot_update_existing_quotes():
    # Test duplicate snapshots against an independent in-memory table.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        conn.exec_driver_sql("""
            CREATE TABLE public.sportybet_odds_history_v1 (
                snapshot_id TEXT, sportybet_event_id TEXT, market TEXT,
                captured_at TIMESTAMP, kickoff TIMESTAMP, quoted_odds REAL,
                home_team TEXT, away_team TEXT,
                PRIMARY KEY(snapshot_id, sportybet_event_id, market)
            )
        """)
        rows, _ = capture.rows_from_cache(cache(), now=NOW)
        conn.execute(capture.INSERT, rows)
        conn.execute(capture.INSERT, rows)
        assert conn.execute(text(
            "SELECT COUNT(*) FROM public.sportybet_odds_history_v1"
        )).scalar() == 2
        altered = [dict(rows[0], quoted_odds=100)]
        conn.execute(capture.INSERT, altered)
        assert conn.execute(text("""
            SELECT quoted_odds FROM public.sportybet_odds_history_v1
            WHERE market='home_win'
        """)).scalar() == 1.8
        assert conn.execute(text("""
            SELECT captured_at FROM public.sportybet_odds_history_v1
            WHERE market='home_win'
        """)).scalar() is not None


def test_sql_only_writes_to_dedicated_history_table():
    sql = str(capture.INSERT).upper()
    assert "PUBLIC.SPORTYBET_ODDS_HISTORY_V1" in sql
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql
    assert "DO UPDATE" not in sql
    assert "PUBLISHED_SLIPS" not in sql
    assert "MARKET_SHADOW_FORECASTS_V1" not in sql
    assert "BOOKMAKER_CACHE" not in sql


class FakeSportyBet:
    def __init__(self, *, complete=True, raise_error=False):
        self.cached_reads = 0
        self.cached_writes = 0
        self.raise_error = raise_error
        self.complete = complete
        self.fetch_was_isolated = False
        self._db_get = self.get_cache
        self._db_set = self.set_cache

    def get_cache(self, *_a, **_kw):
        self.cached_reads += 1
        return None

    def set_cache(self, *_a, **_kw):
        self.cached_writes += 1
        raise AssertionError("Must not persist staging bookmaker cache")

    def fetch_board(self, *, force=False):
        assert force is True
        assert self._db_get("bookmaker") is None
        self._db_set("bookmaker", {})
        self.fetch_was_isolated = True
        payload = cache()
        metadata = dict(payload["metadata"], is_complete=self.complete)
        return {"__meta__": metadata, **payload["fixtures"]}


def test_opt_in_fresh_source_isolated_from_bookmaker_cache(monkeypatch):
    sportybet = FakeSportyBet()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv(
        "BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE",
        "CONFIRM_SOURCE_ONLY_LIVE_FETCH",
    )
    result = capture.fresh_bookmaker_cache(sportybet_module=sportybet)
    assert result["metadata"]["snapshot_id"] == SID
    assert result["fetched_at"] == FETCHED.timestamp()
    assert result["fixtures"]
    assert sportybet.fetch_was_isolated is True
    assert sportybet.cached_reads == 0
    assert sportybet.cached_writes == 0
    assert sportybet._db_get == sportybet.get_cache
    assert sportybet._db_set == sportybet.set_cache


def test_fresh_source_restores_cache_handlers_after_failure(monkeypatch):
    sportybet = FakeSportyBet(complete=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv(
        "BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE",
        "CONFIRM_SOURCE_ONLY_LIVE_FETCH",
    )
    with pytest.raises(ValueError, match="Incomplete live"):
        capture.fresh_bookmaker_cache(sportybet_module=sportybet)
    assert sportybet._db_get == sportybet.get_cache
    assert sportybet._db_set == sportybet.set_cache
    assert sportybet.cached_writes == 0


def test_fresh_source_denies_unapproved_fetch_and_github_actions(monkeypatch):
    sportybet = FakeSportyBet()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="source-only fetch guard"):
        capture.fresh_bookmaker_cache(sportybet_module=sportybet)
    monkeypatch.setenv(
        "BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE",
        "CONFIRM_SOURCE_ONLY_LIVE_FETCH",
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(RuntimeError, match="GitHub Actions"):
        capture.fresh_bookmaker_cache(sportybet_module=sportybet)
    assert sportybet.fetch_was_isolated is False


def test_fresh_source_readonly_preview_has_explicit_network_provenance(
    monkeypatch,
):
    monkeypatch.setattr(capture, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(capture, "fresh_bookmaker_cache", cache)
    dummy = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    result = capture.capture(
        write=False, db_engine=dummy, now=NOW, source="live"
    )
    assert result["mode"] == "DRY_RUN_ONLY"
    assert result["database"] == "betsightly_db_staging"
    assert result["source_mode"] == "live"
    assert result["captured_from_existing_cache_only"] is False
    assert result["network_requests_made"] is True
    assert result["staging_bookmaker_cache_mutated"] is False
    assert result["eligible_prices"] == 2
    assert result["rows_inserted"] == 0
    assert result["clv_proven"] is False
