"""Last-season advanced boxscore opening-week test; no extra score claims."""
import json
from datetime import datetime, timezone
from pathlib import Path

from basketball.research_cli import build_parser
from basketball.research_data import write_games
from basketball.research_advanced_features import _prepare
from basketball.research_early_advanced import (
    _observation, _team_strength, _box_snapshot,
    benchmark, projections, _comparison, VERSION,
)
from tests.test_basketball_coldstart import game


NOW=datetime(2026,10,25,12,tzinfo=timezone.utc)


def fixture_data():
    games=[]
    team=[]
    for season,day in ((2024,"2023-11-01"),
                       (2025,"2024-11-01"),(2026,"2025-11-01")):
        for index in range(240):
            match=game(season*1000+index, season=season,
                       date=day, home="1" if index%2 else "2",
                       away="2" if index%2 else "1")
            home_pts=110+(index%5)
            away_pts=98+(index%4)
            match["home_score"], match["away_score"]=home_pts,away_pts
            games.append(match)
    for k in range(3):
        match=game(27000+k,season=2027,
                   date=f"2026-10-{20+k:02}",home="1",away="2")
        games.append(match)
    match=game(29000,season=2027,date="2026-10-26",
               status="scheduled",home="1",away="2",
               stamp="2026-10-26T20:00:00+00:00")
    games.append(match)
    for match in games:
        if match["status"]!="final":
            continue
        gid=int(match["game_id"])
        for is_home in (True,False):
            side="home" if is_home else "away"
            other="away" if is_home else "home"
            points=match[f"{side}_score"]
            possessions=95+(gid%7)+(0 if is_home else 2)
            team.append({
                "game_id":match["game_id"],
                "team_id":match[f"{side}_id"],
                "opponent_team_id":match[f"{other}_id"],
                "score":points,
                "estimated_possessions":possessions,
                "estimated_offensive_rating":100*points/possessions,
            })
    return games, team


def test_historical_and_upcoming_cohorts_match_existing_early_model(tmp_path):
    games,team=fixture_data()
    write_games(games,tmp_path/"nba_games.jsonl")
    folder=tmp_path/"advanced"
    folder.mkdir()
    for year in (2024,2025,2026,2027):
        (folder/f"team_{year}.json").write_text(json.dumps(
            [x for x in team if int(x["game_id"])//1000==year
             or (year==2027 and 27000<=int(x["game_id"])<28000)]))
    before={p.name:p.read_bytes() for p in
            [tmp_path/"nba_games.jsonl",*folder.glob("team_*.json")]}
    report=benchmark(tmp_path,now=NOW)
    assert report["status"]=="retrospective_diagnostic_only"
    assert report["version"]==VERSION
    assert report["historical_years"]["2025"]["matched_games"]==240
    assert report["historical_years"]["2026"]["matched_games"]==240
    assert report["historical_matched"]["matched_games"]==480
    assert report["future_before_tipoff_eligible"]==1
    assert report["original_future_early_score_eligible"]==1
    assert report["future_preview_samples"][0]["game_id"]=="29000"
    assert report["no_writes"] is True
    after={p.name:p.read_bytes() for p in
           [tmp_path/"nba_games.jsonl",*folder.glob("team_*.json")]}
    assert before==after
    assert not (tmp_path/"opening_score_forecasts.jsonl").exists()


def test_same_day_final_boxscores_cannot_affect_pregame_forecast():
    games,team=fixture_data()
    paired,_=_prepare(games,team,[])
    base,n=projections(games,paired,now=NOW)
    assert n==1
    assert len(base)==1
    # Added final dated the SAME date as scheduled fixture. Even its
    # verified box-score cannot enter the private forecast's prior vector.
    later=game(29001,season=2027,date="2026-10-26",
               home="1",away="2",status="final")
    later["home_score"],later["away_score"]=160,70
    newteam=team+[{
        "game_id":"29001","team_id":side,
        "opponent_team_id":("2" if side=="1" else "1"),
        "score":(160 if side=="1" else 70),
        "estimated_possessions":100,
        "estimated_offensive_rating":(160 if side=="1" else 70),
    } for side in ("1","2")]
    modified=games+[later]
    checked,_=_prepare(modified,newteam,[])
    other,n=projections(modified,checked,now=NOW)
    assert len(other)==1 and n==1
    for key in ("predicted_total","predicted_home_points",
                "predicted_away_points","predicted_home_margin"):
        assert other[0][key] == base[0][key]


def test_cross_season_team_eligibility_and_score_identity():
    games,team=fixture_data()
    paired,_=_prepare(games,team,[])
    result,number=projections(games,paired,now=NOW)
    assert number==1
    assert result[0]["previous_home_boxscore_games"]==240
    assert result[0]["earlier_current_home_boxscore_games"]==3
    assert 150<result[0]["predicted_total"]<280
    assert result[0]["no_bookmaker_market_or_prices"] is True
    assert _team_strength([(99,110,110)]*7,[]) is None
    assert _team_strength([(99,110,110)]*8,[(99,110,110)]*5) is None
    target=games[-2]
    invalid=[x.copy() for x in team]
    for x in invalid:
        if x["game_id"]==target["game_id"] and x["team_id"]==target["home_id"]:
            x["score"]+=5
            break
    import pytest
    with pytest.raises(ValueError,match="identity conflict"):
        _prepare(games,invalid,[])


def test_cli_missing_source_and_false_predictions_blocked(tmp_path):
    assert (build_parser().parse_args(["early-advanced-compare"]).command
            == "early-advanced-compare")
    assert _comparison([])["matched_games"]==0
    assert _comparison([])["targets"]["total"]["advanced_mae"] is None
    assert not list(tmp_path.iterdir())
