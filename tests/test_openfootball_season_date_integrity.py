"""Out-of-season source results cannot contaminate shadow training."""
from datetime import date

from leagues.openfootball_match_history import parse_results, plausible_season_date
from scripts.export_staging_history_training import filter_plausible_season_rows


def test_only_fixtures_with_dates_matching_source_season_are_imported():
    payload = {"matches": [
        {"date": "2025-01-17", "team1": "City", "team2": "United",
         "score": {"ft": [2, 0]}},
        {"date": "2025-08-17", "team1": "City", "team2": "United",
         "score": {"ft": [1, 0]}},
        {"date": "2026-05-24", "team1": "United", "team2": "City",
         "score": [2, 1]},
        {"date": "2026-07-04", "team1": "City", "team2": "United",
         "score": [3, 0]},
    ]}
    rows, report = parse_results(
        payload, "eng.3", "2025-26", as_of=date(2026, 10, 9),
    )
    assert len(rows) == 2
    assert [row["match_date"] for row in rows] == [
        "2025-08-17", "2026-05-24",
    ]
    assert report["rejections"]["out_of_season_date"] == 2


def test_existing_rows_with_wrong_season_are_excluded_from_training():
    rows = [
        {"season": "2025-26", "match_date": date(2025, 1, 17)},
        {"season": "2025-26", "match_date": date(2025, 8, 17)},
        {"season": "2026-27", "match_date": date(2026, 9, 20)},
        {"season": "not-a-season", "match_date": date(2025, 10, 9)},
    ]
    filtered, rejected = filter_plausible_season_rows(rows)
    assert len(filtered) == 2
    assert rejected == 2
    assert filtered[0]["match_date"] == date(2025, 8, 17)
    assert filtered[1]["season"] == "2026-27"
    assert len(rows) == 4  # Audit provenance remains untouched.


def test_season_date_window_is_strict():
    assert plausible_season_date("2025-26", date(2025, 7, 1))
    assert plausible_season_date("2025-26", date(2026, 6, 30))
    assert not plausible_season_date("2025-26", date(2025, 6, 30))
    assert not plausible_season_date("2025-26", date(2026, 7, 1))
    assert not plausible_season_date("2025-29", date(2025, 9, 1))
