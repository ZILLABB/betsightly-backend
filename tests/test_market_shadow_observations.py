"""Proof that shadow forecasts never rewrite official slips or self-grade."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select

from leagues import market_shadow_observations as shadow


@pytest.fixture
def sqlite_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(shadow, "staging_write_gate", lambda **kwargs: "betsightly_db_staging")
    shadow.ensure_table(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _forecast(*, match_id="fixture-1", market="over_1_5", confidence=0.79,
              home="Home United", away="Away Town"):
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    return {
        "match_id": match_id, "market": market,
        "confidence": confidence, "odds": 1.47,
        "odds_are_real": True, "bookable": True,
        "sportybet_event_id": "sb-1",
        "_fixture": {
            "home": {"name": home}, "away": {"name": away},
            "commence_time": kickoff.isoformat(), "league_slug": "eng.1",
        },
    }


def test_record_is_before_kickoff_and_contains_original_price():
    original = _forecast()
    at = datetime.now(timezone.utc)
    observation, reason = shadow.make_observation(
        original, "snapshot-hash", at,
    )
    assert reason == "ready"
    assert observation["probability"] == pytest.approx(0.79)
    assert observation["quoted_odds"] == pytest.approx(1.47)
    assert observation["sportybet_event_id"] == "sb-1"
    assert observation["observed_at"] < observation["kickoff"]


def test_capture_is_first_write_wins_and_keeps_independent_markets(sqlite_db):
    pick = _forecast()
    other_market = _forecast(market="home_or_draw")
    result = shadow.collect(
        [pick, other_market, pick], "original-board", db_engine=sqlite_db,
    )
    assert result["inserted"] == 2
    assert result["refused"]["same_run_duplicate"] == 1
    modified = _forecast(confidence=0.98)
    result2 = shadow.collect([modified], "newer-board", db_engine=sqlite_db)
    assert result2["inserted"] == 0
    assert result2["existing"] == 1
    with sqlite_db.connect() as conn:
        rows = conn.execute(select(shadow.observations)).mappings().all()
    assert len(rows) == 2
    assert all(row["snapshot_id"] == "original-board" for row in rows)
    assert all(float(row["probability"]) != 0.98 for row in rows)


def test_capture_rejects_started_and_unverified_probabilities(sqlite_db):
    pick = _forecast()
    pick["_fixture"]["commence_time"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    result = shadow.collect([pick], "snap", db_engine=sqlite_db)
    assert result["inserted"] == 0
    assert "started_or_too_close_to_kickoff" in result["refused"]
    pick = _forecast(confidence=float("nan"))
    row, reason = shadow.make_observation(
        pick, "snap", datetime.now(timezone.utc),
    )
    assert row is None and reason == "invalid_probability"


def test_cannot_use_estimated_price_as_real_quote():
    pick = _forecast()
    pick["odds_are_real"] = False
    row, reason = shadow.make_observation(
        pick, "snap", datetime.now(timezone.utc),
    )
    assert reason == "ready"
    assert row["quoted_odds"] is None
    assert row["odds_are_real"] is False


def test_verified_result_supports_btts_and_dnb_pushes():
    from leagues.results_checker import _normalize_name

    base = _forecast()
    kickoff = base["_fixture"]["commence_time"]
    date = kickoff[:10]
    key = f"{_normalize_name('Home United')}|{_normalize_name('Away Town')}|{date}"
    scores = {key: {"home_score": 1, "away_score": 1}}
    row, _ = shadow.make_observation(
        base, "snap", datetime.now(timezone.utc),
    )
    assert shadow.verified_result_for_row(row, scores)[0]["outcome"] == 1

    btts, _ = shadow.make_observation(
        _forecast(market="btts_yes"), "snap", datetime.now(timezone.utc),
    )
    assert shadow.verified_result_for_row(btts, scores)[0]["outcome"] == 1

    dnb, _ = shadow.make_observation(
        _forecast(market="dnb_home"), "snap", datetime.now(timezone.utc),
    )
    grade, _ = shadow.verified_result_for_row(dnb, scores)
    assert grade["status"] == "void"
    assert grade["outcome"] is None


def test_ambiguous_score_never_settles():
    forecast, _ = shadow.make_observation(
        _forecast(), "snap", datetime.now(timezone.utc),
    )
    from leagues.results_checker import _normalize_name
    key = ("|".join([
        _normalize_name("Home United"), _normalize_name("Away Town"),
        forecast["kickoff"].date().isoformat(),
    ]))
    grade, reason = shadow.verified_result_for_row(
        forecast, {key: {"ambiguous": True}},
    )
    assert grade is None
    assert reason == "ambiguous_score"


def test_settle_requires_future_eligible_elapsed_kickoff(sqlite_db):
    pick = _forecast(market="btts_no")
    shadow.collect([pick], "snap", db_engine=sqlite_db)
    called = []
    def source(fixtures):
        called.append(fixtures)
        return {}, "espn"
    early = shadow.settle(db_engine=sqlite_db, score_fetcher=source)
    assert early["checked"] == 0
    assert called == []


def test_staging_write_gate_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(
        "scripts.prepare_staging_board_once.preflight",
        lambda: "betsightly_db_staging",
    )
    monkeypatch.delenv("BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE", raising=False)
    pg = type("Pg", (), {"dialect": type("D", (), {"name": "postgresql"})()})()
    monkeypatch.setattr("database.engine", pg)
    with pytest.raises(RuntimeError, match="require CONFIRM_SHADOW_ONLY"):
        shadow.staging_write_gate(db_engine=pg)
    monkeypatch.setenv(
        "BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE", "CONFIRM_SHADOW_ONLY"
    )
    assert shadow.staging_write_gate(db_engine=pg) == "betsightly_db_staging"


def test_verified_shadow_settlement_is_idempotent(sqlite_db):
    from leagues.results_checker import _normalize_name

    pick = _forecast(market="dnb_home")
    observed = datetime.now(timezone.utc)
    capture = shadow.collect(
        [pick], "first-pre-kickoff", db_engine=sqlite_db,
        observed_at=observed,
    )
    assert capture["inserted"] == 1
    kickoff = datetime.fromisoformat(pick["_fixture"]["commence_time"])
    key = (
        f"{_normalize_name('Home United')}|"
        f"{_normalize_name('Away Town')}|{kickoff.date().isoformat()}"
    )
    fetched = []
    def final_scores(fixtures):
        fetched.append(fixtures)
        return {key: {"home_score": 2, "away_score": 1}}, "espn"

    later = kickoff + timedelta(hours=4)
    result = shadow.settle(
        db_engine=sqlite_db, now=later, score_fetcher=final_scores
    )
    assert result["checked"] == 1
    assert result["settled"] == 1
    assert result["unresolved"] == 0
    assert len(fetched) == 1
    report = shadow.evidence_report(db_engine=sqlite_db)
    assert report["markets"]["dnb_home"]["settled"] == 1
    assert report["markets"]["dnb_home"]["brier"] == pytest.approx(0.0441, abs=0.5)
    assert report["market_promotion_allowed"] is False
    again = shadow.settle(
        db_engine=sqlite_db, now=later, score_fetcher=final_scores
    )
    assert again["checked"] == 0
    assert len(fetched) == 1
