"""Basketball score regime experiment must remain chronological and read-only."""
from datetime import date, timedelta

from basketball.research_cli import build_parser
from basketball.research_score_regime import (
    VERSION, CONFIGS, MAX_ABSOLUTE_ADJUSTMENT,
    _league_adjustment, historical_candidates, examine
)
from tests.test_basketball_coldstart import game


def league_fixture(season, day, n, *, level=0, shock=0):
    when = date(season-1, 11, 1)+timedelta(days=day)
    home = str(2*n+1)
    away = str(2*n+2)
    hs = 106 + level + shock + (n % 4) + (day % 5)
    av = 103 + level + shock + (n % 3) - (day % 3)
    return {**game(season*100000 + day*15 + n, season=season,
                   date=when.isoformat(), home=home, away=away,
                   stamp=when.isoformat()+"T20:00:00+00:00"),
            "home_score": hs, "away_score": av}


def sample():
    games=[]
    for season,days,level in ((2024,27,0),(2025,27,3),(2026,6,7)):
        for day in range(days):
            for n in range(15):
                games.append(league_fixture(season,day,n,level=level))
    return games


def test_retrospective_dev_selection_never_uses_2026_outcomes():
    first = sample()
    other = [dict(row) for row in first]
    for g in other:
        if g["season"] == 2026:
            g["home_score"] += 18
            g["away_score"] += 18
    a,b=examine(first),examine(other)
    assert a["selected"] == b["selected"]
    assert a["hypotheses"] == len(CONFIGS)
    assert a["retrospective_2026"]["games"] == 75
    assert a["development_2025"]["games"] == 75
    assert a["genuine_2027_forward_finals_used"] == 0
    assert a["no_writes"] is True
    assert a["model_promotion_approved"] is False


def test_future_games_cannot_leak_into_same_date_regime():
    normal=sample()
    changed=[dict(row) for row in normal]
    for g in changed:
        if g["season"] == 2026 and g["date"] == "2025-11-04":
            g["home_score"] += 100
            g["away_score"] += 100
    def day(rows):
        return {r["game_id"]: r for r in historical_candidates(rows)
                if r["season"] == 2026 and r["date"] == "2025-11-04"}
    original=day(normal)
    altered=day(changed)
    assert len(original) == len(altered) == 15
    for gid,row in original.items():
        assert row["regime_variants"] == altered[gid]["regime_variants"]


def test_league_pace_sample_only_from_earlier_dates():
    rows=historical_candidates(sample())
    y2026=[r for r in rows if r["season"] == 2026]
    start=[r for r in y2026 if r["date"] == "2025-11-01"]
    later=[r for r in y2026 if r["date"] == "2025-11-05"]
    assert len(start) == len(later) == 15
    assert {r["earlier_season_league_finals"] for r in start} == {0}
    assert {r["earlier_season_league_finals"] for r in later} == {60}
    for r in start:
        assert all(v["pace_adjustment"] == 0
                   for v in r["regime_variants"].values())
    assert any(
        r["regime_variants"]["pace_fast"]["pace_adjustment"] != 0
        for r in later)


def test_pace_regime_preserves_margin_and_coherent_points():
    for row in historical_candidates(sample()):
        base=row["regime_variants"]["original_unchanged"]
        for value in row["regime_variants"].values():
            assert abs(value["predicted_home_points"] +
                       value["predicted_away_points"] -
                       value["predicted_total"]) < 0.00001
            assert abs(value["predicted_home_points"] -
                       value["predicted_away_points"] -
                       value["predicted_home_margin"]) < 0.00001
            assert abs(value["predicted_home_margin"] -
                       base["predicted_home_margin"]) < 0.00001


def test_bounds_missing_and_small_samples(tmp_path):
    assert _league_adjustment(210, 3000, 4, 20) == 0
    assert _league_adjustment(210, 3000, 20, None) == 0
    assert _league_adjustment(210, 3000, 20, 20) <= MAX_ABSOLUTE_ADJUSTMENT
    assert examine([])["status"] == "insufficient_development_cohort"
    assert examine([])["no_writes"] is True
    assert (build_parser().parse_args(
        ["opening-score-regime"]).command == "opening-score-regime")
    assert not list(tmp_path.iterdir())


def test_source_games_not_mutated():
    games=sample()
    before=[dict(x) for x in games]
    result=examine(games)
    assert result["version"] == VERSION
    assert result["no_saved_forecasts_rewritten"] is True
    assert result["original_model_unchanged"] is True
    assert result["retrospective_2026"][
        "positive_total_uncertainty_interval"] in (False, True, None)
    assert games == before
