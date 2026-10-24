"""Stage 3B–C: verified team/player boxscore, official injury snapshots,
no pregame leakage and independent private advanced research."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from basketball.research_advanced_data import (
    _process,normalize_team,normalize_player,fetch_advanced,
    advanced_coverage,_read_parquet,
)
from basketball.research_advanced_features import (
    make_advanced_rows,FEATURE_COLUMNS,from_home,
)
from basketball.research_advanced_model import build_candidate,run_shadow
from basketball.research_data import write_games
from basketball.research_injury_reports import (
    select_report,_datetime_from_name,capture_injury,injury_status,
    parse_pdf_players,
)
UTC=timezone.utc


def fixture(i=1,season=2026,day="2026-04-10",status="final"):
    return {
        "game_id":str(400000+i),"date":day,"season":season,
        "status":status,"home_id":"1","away_id":"2",
        "home_name":"Home","away_name":"Away",
        "home_score":111 if status=="final" else None,
        "away_score":99 if status=="final" else None,
        "start_utc":day+"T21:00:00+00:00","postseason":False,
        "source":"sportsdataverse:espn_nba_schedules:v1",
        "retrieved_at":"2026-10-24T12:00:00+00:00",
    }


def raw_team(g,side):
    home=side=="home"
    return {
        "game_id":g["game_id"],"season":g["season"],
        "season_type":2,"team_id":1 if home else 2,
        "opponent_team_id":2 if home else 1,
        "team_score":111 if home else 99,
        "field_goals_attempted":90,"free_throws_attempted":19,
        "offensive_rebounds":12,"total_turnovers":14,
        "field_goals_made":43,"three_point_field_goals_made":12,
        "three_point_field_goals_attempted":30,
    }


def raw_player(g,side,i):
    return {
        "game_id":g["game_id"],"season":g["season"],
        "season_type":2,"team_id":1 if side=="home" else 2,
        "athlete_id":10000+(0 if side=="home" else 100)+i,
        "athlete_display_name":"Test Player "+str(i),
        "minutes":24.0,"points":14 if i%2 else 16,
        "did_not_play":False,
    }


def normalized(games):
    from basketball.research_advanced_data import normalize_team,normalize_player
    teams=[normalize_team(raw_team(g,side),season=g["season"])
           for g in games for side in ("home","away") if g["status"]=="final"]
    players=[normalize_player(raw_player(g,side,i),season=g["season"])
             for g in games for side in ("home","away") for i in range(10)
             if g["status"]=="final"]
    return teams,players


def test_derived_possessions_and_metrics_are_boxscore_based():
    entry=normalize_team(raw_team(fixture(),"home"),season=2026)
    assert entry["estimated_possessions"]==100.36
    assert entry["estimated_offensive_rating"]==round(111*100/100.36,4)
    assert entry["e_fg"]==round((43+6)/90,5)
    assert 0<entry["three_rate"]<1


def test_score_and_opponent_join_requires_exact_espn_fixture():
    g=fixture()
    teams,players=normalized([g])
    rows,report=make_advanced_rows([g],teams,players)
    assert rows==[]
    assert report["exact_joined_final_games"]==1
    with pytest.raises(ValueError,match="conflict"):
        altered=[{**teams[0],"score":109},teams[1]]
        make_advanced_rows([g],altered,players)


def test_game_features_never_see_same_day_box_scores():
    dates=[(datetime(2026,3,1,tzinfo=UTC)+timedelta(days=i)).date().isoformat()
           for i in range(10)]
    games=[fixture(i=i+1,day=day) for i,day in enumerate(dates)]
    games.append(fixture(i=99,day="2026-03-11",status="scheduled"))
    teams,players=normalized(games)
    out,report=make_advanced_rows(games,teams,players)
    target=next(r for r in out if r["game_id"]==str(400099))
    assert len(target["features"])==len(FEATURE_COLUMNS)==30
    changed=fixture(i=50,day="2026-03-11")
    t2,p2=normalized([changed])
    changed_rows,_=make_advanced_rows(games+[changed],teams+t2,players+p2)
    assert next(r for r in changed_rows if r["game_id"]==str(400099)
                )["features"]==target["features"]


def test_feature_coverage_requires_at_least_five_prior_complete_games():
    g=[fixture(i=i,day=(datetime(2026,3,1,tzinfo=UTC)+
       timedelta(days=i)).date().isoformat()) for i in range(4)]
    future=fixture(i=90,day="2026-03-05",status="scheduled")
    teams,players=normalized(g)
    rows,_=make_advanced_rows(g+[future],teams,players)
    assert not rows


def test_advanced_feature_refuses_incomplete_roster_minutes():
    games=[fixture(i=i,day=(datetime(2026,3,1,tzinfo=UTC)+
           timedelta(days=i)).date().isoformat()) for i in range(7)]
    teams,players=normalized(games)
    players=[p for p in players if p["athlete_id"] not in
             {10001,10101,10002,10102}]
    rows,report=make_advanced_rows(games,teams,players)
    assert isinstance(rows,list)
    assert report["advanced_eligible_rows"]<=report["baseline_eligible_rows"]


def test_ingestion_fails_closed_on_incomplete_team_identity_and_score():
    g=fixture()
    games={g["game_id"]:g}
    fakebytes=b"PAR1"+b"x"*120
    class Response:
        headers={"Content-Length":str(len(fakebytes))}
        def read(self,n):return fakebytes
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def opener(*args,**kwargs):return Response()
    rows=[raw_team(g,"home"),raw_team(g,"away")]
    normalized,info=_process(kind="team",season=2026,fixtures=games,
                             loader=lambda data,required:rows,opener=opener)
    assert len(normalized)==2
    assert info["covered_final_games"]==1
    bad=[{**rows[0],"team_score":112},rows[1]]
    with pytest.raises(ValueError,match="differs"):
        _process(kind="team",season=2026,fixtures=games,
                 loader=lambda data,required:bad,opener=opener)


def test_source_ingestion_preserves_prior_assets_on_failure(tmp_path):
    g=fixture()
    write_games([g],tmp_path/"nba_games.jsonl")
    box=tmp_path/"advanced"
    box.mkdir()
    original=box/"team_2026.json"
    original.write_text('{"previous":"safe"}')
    class Response:
        headers={}
        def read(self,n):return b"PAR1"+b"x"*120
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def opener(*args,**kwargs):return Response()
    with pytest.raises(ValueError,match="differs"):
        fetch_advanced(home=tmp_path,seasons=[2026],kinds=("team",),
                       loader=lambda *args:[{**raw_team(g,"home"),
                                              "team_score":150},raw_team(g,"away")],
                       opener=opener)
    assert original.read_text()=='{"previous":"safe"}'


def test_player_box_dnp_not_falsely_current_injury():
    g=fixture()
    dnp={**raw_player(g,"home",1),"did_not_play":True,
         "minutes":None,"points":None}
    p=normalize_player(dnp,season=2026)
    assert p["minutes"]==0
    assert p["did_not_play"] is True
    assert "injured" not in p


def test_injury_url_selection_filters_future_foreign_and_bad_paths():
    html='''<a href="https://evil.example/report.pdf">E</a>
    <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-24_01_15PM.pdf">A</a>
    <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-24_09_15AM.pdf">B</a>'''
    when=datetime(2026,10,24,14,0,tzinfo=UTC)
    result=select_report(html,now=when)
    assert "09_15AM" in result["source_url"]
    assert _datetime_from_name(result["source_url"])<=when
    with pytest.raises(ValueError,match="No valid"):
        select_report(html,now=datetime(2026,10,23,tzinfo=UTC))


def test_pdf_archive_timestamp_not_download_time(tmp_path):
    raw=b"%PDF-1.7\n"+b"x"*120
    page=('''<a href="https://ak-static.cms.nba.com/referee/injury/'''
          '''Injury-Report_2026-10-24_05_00AM.pdf">5</a>''').encode()
    class Response:
        headers={}
        def __init__(self,data):self.data=data
        def read(self,n):return self.data
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def opener(req,timeout):
        return Response(page if "official.nba.com" in req.full_url else raw)
    when=datetime(2026,10,24,14,0,tzinfo=UTC)
    def parser(blob):
        assert blob==raw
        return [],{"status":"unparsed","reason":"test_pdf_fixture"}
    result=capture_injury(tmp_path,now=when,opener=opener,parser=parser)
    assert result["status"]=="archived"
    assert result["player_rows"]==0
    latest=injury_status(tmp_path)
    assert latest["snapshots"]==1
    assert latest["status"]=="unparsed"
    assert latest["pregame_model_integration"] is False
    again=capture_injury(tmp_path,now=when,opener=opener,parser=parser)
    assert again["snapshot_hash"]==result["snapshot_hash"]
    assert injury_status(tmp_path)["snapshots"]==1


def test_advanced_candidate_requires_real_history_no_fabricated_metrics(tmp_path):
    write_games([fixture()],tmp_path/"nba_games.jsonl")
    blocked=build_candidate(tmp_path)
    assert blocked["status"]=="blocked"
    assert not (tmp_path/"advanced"/"shadow_model.joblib").exists()
    assert run_shadow(tmp_path)["status"]=="not_configured"
    assert advanced_coverage(tmp_path)["team_seasons"]==0


def test_windows_missing_iana_tzdata_has_actionable_error(monkeypatch):
    """Do not guess a fixed ET offset if ZoneInfo has no Windows tzdb."""
    from zoneinfo import ZoneInfoNotFoundError
    import basketball.research_injury_reports as reports

    def missing(_name):
        raise ZoneInfoNotFoundError("No time zone found with key America/New_York")

    monkeypatch.setattr(reports, "ZoneInfo", missing)
    html = (
        '<a href="https://ak-static.cms.nba.com/referee/injury/'
        'Injury-Report_2026-10-24_05_00AM.pdf">Official NBA report</a>'
    )
    with pytest.raises(RuntimeError, match="pip install tzdata"):
        reports.select_report(html, now=datetime(2026, 10, 24, 14, tzinfo=UTC))


def test_missing_windows_timezone_never_stops_v1_pregame_sidecar(
    tmp_path, monkeypatch
):
    """The optional injury feed must not turn a healthy v1 run into failed."""
    from basketball.research_automation import _advanced_sidecar
    import basketball.research_injury_reports as reports

    def unavailable(*_args, **_kwargs):
        raise RuntimeError(
            "NBA injury archive needs IANA tzdata: python -m pip install tzdata"
        )

    monkeypatch.setattr(reports, "capture_injury", unavailable)
    report = _advanced_sidecar(
        tmp_path, datetime(2026, 10, 24, 20, tzinfo=UTC)
    )
    assert report["injury"]["status"] == "unavailable"
    assert "tzdata" in report["injury"]["error"]
    assert report["shadow"]["status"] == "not_configured"
