from pathlib import Path

import pandas as pd
import pytest

from leagues.historical_replay import (
    _combine_summaries, devig_1x2, devig_two_way, load_and_deduplicate, replay, settle_markets,
)


def _row(date, home="A", away="B", hs=1, aws=0, league="L"):
    return {"date":pd.Timestamp(date),"home":home,"away":away,"home_score":hs,
            "away_score":aws,"league":league,"season":"2025","source":"test",
            "source_row_id":1,"odds_home":2.0,"odds_draw":3.5,"odds_away":4.0,
            "odds_over25":1.9,"odds_under25":1.9,"provenance":[{"source":"test"}]}


def test_complete_markets_are_devigged():
    values, overround = devig_1x2(2, 4, 4)
    assert sum(values.values()) == pytest.approx(1)
    assert values["home_win"] == pytest.approx(.5)
    assert overround == pytest.approx(1)
    pair, _ = devig_two_way(2, 2)
    assert pair == pytest.approx((.5, .5))


@pytest.mark.parametrize("prices", [(0,2,2),(1,2,2),("bad",2,2),(float("nan"),2,2)])
def test_malformed_odds_are_rejected(prices):
    assert devig_1x2(*prices) == (None, None)


def test_every_binary_market_and_dnb_push_settle_correctly():
    home = settle_markets(2, 1)
    assert home["home_win"] == home["home_or_draw"] == home["home_over_1_5"] == 1
    assert home["over_2_5"] == home["under_3_5"] == home["btts_yes"] == 1
    draw = settle_markets(1, 1)
    assert draw["dnb_home"] is None and draw["dnb_away"] is None
    assert draw["home_or_away"] == 0 and draw["away_or_draw"] == 1


def test_duplicate_identity_is_deterministic_and_provenance_is_preserved(tmp_path:Path):
    api=tmp_path/"api.csv"; git=tmp_path/"git.csv"
    pd.DataFrame([{"home_team":"A","away_team":"B","date":"2025-01-01","home_score":1,"away_score":0,
                   "league_name":"L","season":2025,"avg_odds_home":2,"avg_odds_draw":3,"avg_odds_away":4,
                   "avg_odds_over25":1.9,"avg_odds_under25":1.9}]).to_csv(api,index=False)
    pd.DataFrame([{"HomeTeam":"A","AwayTeam":"B","MatchDate":"2025-01-01","FTHome":1,"FTAway":0,
                   "Division":"L","OddHome":None,"OddDraw":None,"OddAway":None,"Over25":None,"Under25":None}]).to_csv(git,index=False)
    rows,meta=load_and_deduplicate(api,git)
    assert len(rows)==1 and meta["duplicates_detected"]==1
    assert rows[0]["source"]=="api_football" and len(rows[0]["provenance"])==2


def test_same_day_and_future_results_never_enter_prior_base(monkeypatch):
    seen=[]
    def fake_predict(fixture,base,elo_probs=None):
        seen.append(base["matches"])
        return {"probabilities":{m:.6 for m in settle_markets(0,0)}}
    monkeypatch.setattr("leagues.historical_replay.predict",fake_predict)
    rows=[_row("2025-01-01",home="A",away="B"),_row("2025-01-01",home="C",away="D"),
          _row("2025-01-02",home="E",away="F")]
    replay(rows)
    assert seen[:2]==[0,0]
    assert seen[2]==0  # fewer than the production minimum uses neutral fallback


def test_replay_metrics_buckets_leagues_fidelity_and_determinism():
    rows=[_row(f"2025-01-{day:02d}",home=f"A{day}",away=f"B{day}",hs=day%3,aws=day%2)
          for day in range(1,16)]
    first=replay(rows); second=replay(rows)
    assert first["market_summary"]==second["market_summary"]
    assert first["run"]["fidelity_counts"]["MARKET_REPLAY"]==15
    assert first["market_summary"]["over_1_5"]["n"]==15
    assert first["market_summary"]["over_1_5"]["brier"] is not None
    assert first["calibration_buckets"]["over_1_5"]
    assert "l" in first["league_market_summary"]["over_1_5"]
    assert "2025" in first["season_market_summary"]["over_1_5"]


def test_missing_ou_is_reduced_fidelity_and_missing_all_odds_is_insufficient():
    reduced=_row("2025-01-01"); reduced["odds_over25"]=reduced["odds_under25"]=None
    missing=_row("2025-01-02"); missing.update(odds_home=None,odds_draw=None,odds_away=None,
                                                odds_over25=None,odds_under25=None)
    result=replay([reduced,missing])
    assert result["run"]["fidelity_counts"]=={"DERIVED_REPLAY":1,"INSUFFICIENT":1}
    assert result["run"]["predictions_generated"]==1

def test_recency_summary_is_sample_weighted():
    value=_combine_summaries([{"n":1,"predicted":.9,"actual":1,"calibration_error":-.1,"brier":.01,"log_loss":.1},
                              {"n":3,"predicted":.5,"actual":.4,"calibration_error":.1,"brier":.25,"log_loss":.7}])
    assert value["n"]==4 and value["predicted"]==pytest.approx(.6)
