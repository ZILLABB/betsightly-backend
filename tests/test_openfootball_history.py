from datetime import date

from leagues.openfootball_history import (
    SourceFile,
    classify_source_path,
    deduplicate_matches,
    historical_cutoff,
    parse_openfootball_text,
)


def source(league_id=2, competition="UEFA Champions League", season="2024-25"):
    return SourceFile(
        repo="champions-league",
        path="2024-25/cl.txt",
        league_id=league_id,
        competition=competition,
        season=season,
        commit_sha="abc123",
    )


def world_cup_source(season: str):
    return SourceFile(
        repo="worldcup",
        path=f"{season}--test/cup.txt",
        league_id=1,
        competition="FIFA World Cup",
        season=season,
        commit_sha="abc123",
    )


def test_classifies_sudamericana_files_as_league_11():
    item = classify_source_path(
        "south-america",
        "copa-libertadores/2025_copas.txt",
        "deadbeef",
    )
    assert item is not None
    assert item.league_id == 11
    assert item.competition == "Copa Sudamericana"


def test_parses_results_and_inherits_year():
    text = """= UEFA Champions League 2024/25

  Tue Sep 17 2024
    18:45  BSC Young Boys (SUI) v Aston Villa FC (ENG) 0-3 (0-2)
  Wed Sep 18
           AC Milan (ITA) v Liverpool FC (ENG) 1-3 (1-2)
"""
    rows, stats = parse_openfootball_text(text, source())
    assert len(rows) == 2
    assert rows[0].date == "2024-09-17"
    assert rows[0].home_team == "BSC Young Boys"
    assert rows[0].away_team == "Aston Villa FC"
    assert rows[1].date == "2024-09-18"
    assert stats["matches"] == 2


def test_rolls_cross_year_season_once():
    text = """= UEFA Champions League 2024/25

  Wed Dec 11 2024
    21:00  Team A (ENG) v Team B (ESP) 2-0 (1-0)
  Tue Jan 21
    21:00  Team C (ITA) v Team D (GER) 1-1 (0-1)
"""
    rows, _ = parse_openfootball_text(text, source())
    assert [row.date for row in rows] == ["2024-12-11", "2025-01-21"]


def test_single_year_competition_never_rolls_to_next_year():
    src = SourceFile(
        repo="south-america",
        path="copa-libertadores/2026_copal.txt",
        league_id=13,
        competition="Copa Libertadores",
        season="2026",
        commit_sha="abc123",
    )
    text = """Tue Nov 3 2026
  21:30 Team A (ARG) v Team B (BRA) 1-0 (0-0)
Tue Jan 5
  21:30 Team C (ARG) v Team D (BRA) 2-0 (1-0)
"""
    rows, _ = parse_openfootball_text(text, src)
    assert [row.date for row in rows] == ["2026-11-03", "2026-01-05"]


def test_world_cup_2014_v_format_with_timezone_and_venue():
    text = """Thu Jun 12
  17:00 UTC-3  Brazil v Croatia 3-1 (1-1) @ Arena de Sao Paulo
"""
    rows, _ = parse_openfootball_text(text, world_cup_source("2014"))
    assert len(rows) == 1
    assert rows[0].home_team == "Brazil"
    assert rows[0].away_team == "Croatia"
    assert rows[0].home_score == 3
    assert rows[0].away_score == 1


def test_world_cup_2018_score_middle_format():
    text = """Thu Jun 14
  18:00 UTC+3 Russia 5-0 (2-0) Saudi Arabia @ Luzhniki Stadium
"""
    rows, _ = parse_openfootball_text(text, world_cup_source("2018"))
    assert len(rows) == 1
    assert rows[0].home_team == "Russia"
    assert rows[0].away_team == "Saudi Arabia"


def test_world_cup_2022_score_middle_format_without_timezone():
    text = """Sun Nov 20
  19:00 Qatar 0-2 (0-2) Ecuador @ Al Bayt Stadium
"""
    rows, _ = parse_openfootball_text(text, world_cup_source("2022"))
    assert len(rows) == 1
    assert rows[0].home_team == "Qatar"
    assert rows[0].away_team == "Ecuador"


def test_penalty_rows_fail_closed_instead_of_using_penalty_score():
    text = """= Copa Sudamericana 2025

  Tue Mar 4 2025
    21:30  Universidad Católica (CHI) v Palestino (CHI) 4-5 pen. (1-1, 0-1)
    23:00  Team A (ARG) v Team B (BRA) 2-1 (1-0)
"""
    src = SourceFile(
        repo="south-america",
        path="copa-libertadores/2025_copas.txt",
        league_id=11,
        competition="Copa Sudamericana",
        season="2025",
        commit_sha="abc123",
    )
    rows, stats = parse_openfootball_text(text, src)
    assert len(rows) == 1
    assert rows[0].home_team == "Team A"
    assert stats["excluded_knockout_score_semantics"] == 1


def test_historical_cutoff_never_includes_today_or_future():
    assert historical_cutoff(2026, today=date(2026, 9, 27)) == date(2026, 9, 26)
    assert historical_cutoff(2025, today=date(2026, 9, 27)) == date(2025, 12, 31)


def test_deduplication_rejects_conflicting_scores():
    text_a = """Tue Sep 17 2024
    18:45 Team A (ENG) v Team B (ESP) 1-0 (0-0)
"""
    text_b = """Tue Sep 17 2024
    18:45 Team A (ENG) v Team B (ESP) 2-0 (0-0)
"""
    rows_a, _ = parse_openfootball_text(text_a, source())
    rows_b, _ = parse_openfootball_text(text_b, source())

    try:
        deduplicate_matches(rows_a + rows_b)
    except ValueError as exc:
        assert "Conflicting historical fixture" in str(exc)
    else:
        raise AssertionError("conflicting duplicate should fail closed")
