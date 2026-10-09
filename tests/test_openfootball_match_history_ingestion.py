"""Real OpenFootball score parser and staging ingestion safety."""
from datetime import date

import pytest

from leagues.openfootball_match_history import (
    LEAGUES, _fulltime, parse_results, source_url,
)
from scripts import ingest_staging_historical_results as ingest


def example_rows():
    return {
        "name": "English Premier League",
        "matches": [
            {"date": "2025-08-15", "team1": "Liverpool",
             "team2": "Bournemouth", "score": {"ft": [4, 2], "ht": [1, 0]}},
            {"date": "2025-09-01", "team1": "Arsenal",
             "team2": "Chelsea", "score": [1, 1]},
            {"date": "2026-10-09", "team1": "Arsenal",
             "team2": "Chelsea", "score": {"ft": [3, 1]}},
            {"date": "2025-08-16", "team1": "Man City",
             "team2": "Man Utd"},
            {"date": "2025-09-02", "team1": "Unknown",
             "team2": "Unknown", "score": [2, 0]},
            {"date": "2025-09-03", "team1": "X",
             "team2": "Y", "score": [False, 2]},
        ],
    }


def test_real_results_are_validated_chronologically_and_deduplicated():
    rows, report = parse_results(
        example_rows(), "eng.1", "2025-26",
        as_of=date(2026, 10, 9), source_hash="testsha",
    )
    assert len(rows) == 2
    assert {r["home_score"] for r in rows} == {4, 1}
    assert all(row["match_date"] < "2026-10-09" for row in rows)
    assert all(row["source_license"] == "CC0-1.0" for row in rows)
    assert all(row["source_sha256"] == "testsha" for row in rows)
    assert report["rejections"]["unfinished_or_future"] == 1
    assert report["rejections"]["unsettled_or_invalid_score"] == 2
    assert report["rejections"]["invalid_teams"] == 1


def test_same_match_conflicting_scores_fail_closed():
    payload = {"matches": [
        {"date": "2025-08-01", "team1": "A", "team2": "B", "score": [1, 0]},
        {"date": "2025-08-01", "team1": "A", "team2": "B", "score": [0, 1]},
    ]}
    with pytest.raises(ValueError, match="Conflicting"):
        parse_results(payload, "eng.1", "2025-26", as_of=date(2026, 10, 9))


def test_score_parser_rejects_unfinished_and_malformed():
    assert _fulltime({"ft": [3, 2]}) == (3, 2)
    assert _fulltime([0, 0]) == (0, 0)
    assert _fulltime({"ht": [1, 0]}) is None
    assert _fulltime({"ft": [True, 0]}) is None
    assert _fulltime({"ft": [-1, 0]}) is None
    assert _fulltime({"ft": [31, 0]}) is None


def test_source_paths_whitelisted_not_arbitrary_urls():
    assert source_url("eng.1", "2025-26").endswith("/2025-26/en.1.json")
    for slug in ("not-supported", "../secrets", "srl.1"):
        with pytest.raises(ValueError):
            source_url(slug, "2025-26")
    for season in ("2025", "../../pwd", "2025-29"):
        with pytest.raises(ValueError):
            source_url("eng.1", season)
    with pytest.raises(ValueError):
        source_url("eng.1", "2025-26", revision="../branch")


def test_default_ingestion_is_dry_run_and_never_writes(monkeypatch):
    monkeypatch.setattr(ingest, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(ingest, "fetch_results", lambda *args, **kwargs: (
        parse_results(example_rows(), "eng.1", "2025-26",
                      as_of=date(2026, 10, 9))[0],
        {"source": "test"},
    ))
    report = ingest.ingest(leagues=["eng.1"], years=1)
    assert report["dry_run"] is True
    assert report["new_rows_written_staging"] == 0
    assert report["source_successes"] == 1
    assert report["production_unchanged"] is True


def test_wrong_environment_fails_before_any_external_fetch(monkeypatch):
    monkeypatch.setattr(ingest, "preflight", lambda: (_ for _ in ()).throw(
        RuntimeError("wrong database")
    ))
    monkeypatch.setattr(ingest, "fetch_results",
                        lambda *args, **kwargs: pytest.fail("should not fetch"))
    with pytest.raises(RuntimeError, match="wrong database"):
        ingest.ingest(leagues=["eng.1"], years=2, write_staging=True)


def test_training_season_bounds_are_finite():
    assert ingest.seasons_to_import(2, today=date(2026, 10, 9)) == [
        "2025-26", "2026-27",
    ]
    with pytest.raises(ValueError):
        ingest.seasons_to_import(30)
    assert "eng.1" in LEAGUES
