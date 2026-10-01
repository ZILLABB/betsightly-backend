from pathlib import Path

import pandas as pd

from leagues.historical_warehouse import (
    build_manifest,
    build_rows,
    stable_match_id,
)
from scripts import fetch_history_fdc_v2 as fdc


def _row(**overrides):
    row = {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "date": "2026-09-27",
        "home_score": 2,
        "away_score": 1,
        "league_id": 39,
        "league_name": "Premier League",
        "country": "England",
        "league_tier": 1,
        "season": 2026,
        "avg_odds_home": 1.90,
        "avg_odds_draw": 3.50,
        "avg_odds_away": 4.20,
        "avg_odds_over25": 1.80,
        "avg_odds_under25": 2.00,
    }
    row.update(overrides)
    return row


def test_stable_match_id_does_not_depend_on_score_or_odds():
    one = _row(home_score=1, avg_odds_home=1.8)
    two = _row(home_score=4, avg_odds_home=2.2)

    assert stable_match_id(one) == stable_match_id(two)


def test_legacy_rows_are_never_mislabeled_as_exact_closing_provenance():
    frame = pd.DataFrame([_row()])
    rows, quarantine, stats = build_rows(
        frame,
        input_path=Path("data/api-football/matches.csv"),
    )

    assert not quarantine
    assert stats.output_rows == 1
    out = rows[0]
    assert out["source_provider"] == "football-data.co.uk"
    assert out["provenance_quality"] == "LEGACY_INFERRED"
    assert out["odds_home_snapshot_type"] == "UNKNOWN_LEGACY_MIXED"
    assert out["odds_home_source_column"] == ""


def test_conflicting_duplicate_results_are_quarantined():
    frame = pd.DataFrame([
        _row(home_score=1),
        _row(home_score=2),
    ])

    rows, quarantine, stats = build_rows(
        frame,
        input_path=Path("legacy.csv"),
    )

    assert rows == []
    assert len(quarantine) == 2
    assert stats.conflicting_keys == 1


def test_exact_duplicate_prefers_exact_provenance():
    inferred = _row()
    exact = _row(
        source_provider="football-data.co.uk",
        source_dataset="football-data.co.uk CSV",
        source_url="https://example.test/E0.csv",
        source_file="2526/E0.csv",
        source_row_id="10",
        source_league_code="E0",
        provenance_quality="EXACT_SOURCE_ROW",
        fetched_at="2026-09-27T00:00:00+00:00",
        odds_home_source_column="AvgCH",
        odds_home_snapshot_type="CLOSING",
    )
    frame = pd.DataFrame([inferred, exact])

    rows, quarantine, stats = build_rows(
        frame,
        input_path=Path("mixed.csv"),
    )

    assert not quarantine
    assert stats.duplicate_keys == 1
    assert rows[0]["provenance_quality"] == "EXACT_SOURCE_ROW"
    assert rows[0]["odds_home_snapshot_type"] == "CLOSING"


def test_fetcher_prefers_closing_labeled_column_and_records_it():
    value, column, snapshot = fdc._pick(
        {"AvgCH": "1.95", "AvgH": "1.80"},
        ["AvgCH", "AvgH"],
    )

    assert value == "1.95"
    assert column == "AvgCH"
    assert snapshot == "CLOSING"


def test_nonclosing_fallback_is_not_called_closing():
    value, column, snapshot = fdc._pick(
        {"AvgH": "1.80"},
        ["AvgCH", "AvgH"],
    )

    assert value == "1.80"
    assert column == "AvgH"
    assert snapshot == "UNSPECIFIED"


def test_manifest_keeps_odds_coverage_visible():
    frame = pd.DataFrame([_row(avg_odds_over25="", avg_odds_under25="")])
    rows, quarantine, stats = build_rows(
        frame,
        input_path=Path("legacy.csv"),
    )
    manifest = build_manifest(
        rows,
        quarantine,
        stats,
        input_path=Path("legacy.csv"),
    )

    assert manifest["odds_coverage"]["complete_1x2_pct"] == 100.0
    assert manifest["odds_coverage"]["complete_ou25_pct"] == 0.0


def test_legacy_fetcher_entrypoint_help_runs_without_network():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/fetch_history_fdc.py", "--help"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "--legacy-output" in result.stdout
    assert "--recent" in result.stdout
