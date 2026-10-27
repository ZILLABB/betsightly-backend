"""Basketball settlement changes preserve immutable full-game market intent."""
from datetime import datetime, timezone, timedelta
import time

from growth import basketball_jackpot as bj
from growth import basketball_settlement as bs
from growth.basketball_market_grades import grade_team_total


def test_exact_team_total_sides_and_overtime():
    reference={"market_id":"227","specifier":"total=111.5",
               "outcome_id":"12","side":"home"}
    assert grade_team_total(reference,home_points=112,away_points=110)=="won"
    assert grade_team_total({**reference,"outcome_id":"13"},
                            home_points=112,away_points=110)=="lost"
    assert grade_team_total({**reference,"specifier":"total=112"},
                            home_points=112,away_points=110)=="void"
    away={"market_id":"228","specifier":"total=109.5","side":"away","outcome_id":"12"}
    assert grade_team_total(away,home_points=112,away_points=110)=="won"
    assert grade_team_total({**away,"outcome_id":"13"},home_points=112,away_points=110)=="lost"


def test_unverified_market_identity_never_inherits_other_team_result():
    template={"market_id":"227","specifier":"total=105.5","side":"away","outcome_id":"12"}
    assert grade_team_total(template,home_points=130,away_points=90) is None
    assert grade_team_total({**template,"side":"home","market_id":"228"},
                            home_points=130,away_points=90) is None
    assert grade_team_total({**template,"side":"home","market_id":"223"},
                            home_points=130,away_points=90) is None
    assert grade_team_total({**template,"side":"home","market_id":"225"},
                            home_points=130,away_points=90) is None
    assert grade_team_total({**template,"side":"home","outcome_id":"1"},
                            home_points=130,away_points=90) is None
    assert grade_team_total({**template,"side":"home","specifier":"total=NaN"},
                            home_points=130,away_points=90) is None


def test_settler_provides_final_score_provenance_only_for_exact_team_line():
    full={"source":"ESPN_NBA_FINAL","source_event_id":"40190001","home_score":112,"away_score":110}
    leg={"market_id":"228","specifier":"total=111.5","side":"away","outcome_id":"13"}
    finished=bs.settle_leg(leg,full)
    assert finished["result"]=="won"
    assert finished["score_source"]=="ESPN_NBA_FINAL"
    assert finished["score"]=={"home":112,"away":110}
    assert bs.settle_leg({**leg,"side":"home"},full).get("result") is None


def test_no_new_market_can_be_submitted_until_full_provider_acceptance():
    due=(time.time()+3600)*1000
    board={"metadata":{"snapshot_id":"audit-gated"},"fixtures":[{
        "event_id":"sr:match:123456","home_team":"Boston Celtics",
        "away_team":"New York Knicks","competition":"NBA",
        "kickoff_ms":due,"markets":[{
          "market_id":"227","specifier":"total=110.5","label":"Home team total",
          "outcomes":[{"outcome_id":"12","odds":1.92,"label":"Over 110.5","side":"home"}],
        }]
    }]}
    request={"selections":[{"event_id":"sr:match:123456","market_id":"227",
       "specifier":"total=110.5","outcome_id":"12"}],"target_odds":2}
    result=bj._select(request,board)
    assert result["status"]=="EXACT_MARKETS_UNAVAILABLE"
    assert result["matched"] == []
    assert result["unmatched"][0]["reason"]=="MARKET_SETTLEMENT_NOT_VERIFIED"
    assert result["share_code"] is None
