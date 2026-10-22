"""Offline confidence/feasibility tests; no bookmaker network access."""
import sys
import types

from growth.jackpot_optimizer import capacity, optimize
from growth.private_jackpot import auto_booking_request, candidate_board, optimize_request


def _examples():
    return [
        dict(selection_id="a:home_win",match_id="a",market="home_win",
             home_team="A",away_team="B",odds=1.5,
             selection_probability=.91,bookable=True),
        dict(selection_id="a:over_2_5",match_id="a",market="over_2_5",
             home_team="A",away_team="B",odds=2.0,
             selection_probability=.70,bookable=True),
        dict(selection_id="b:away_win",match_id="b",market="away_win",
             home_team="C",away_team="D",odds=2.1,
             selection_probability=.77,bookable=True),
        dict(selection_id="c:over_1_5",match_id="c",market="over_1_5",
             home_team="E",away_team="F",odds=1.4,
             selection_probability=.86,bookable=True),
    ]


def test_capacity_counts_distinct_fixtures_not_market_rows():
    rows=_examples()
    rows.append(dict(selection_id="c:home_under_1_5",match_id="c",
                     market="home_under_1_5",odds=99.0,selection_probability=.9))
    bounds=capacity(rows)
    assert bounds["distinct_fixture_count"]==3
    assert bounds["maximum_reference_odds"]==round(2.0*2.1*1.4,3)
    assert bounds["maximum_legs_available"]==3


def test_optimizer_fails_closed_if_impossible_or_too_few_legs():
    rows=_examples()
    assert optimize(rows,100000)["status"]=="UNREACHABLE"
    assert optimize(rows,5.0,1)["status"]=="UNREACHABLE"


def test_optimizer_auto_selects_distinct_games_above_target():
    rows=_examples()
    answer=optimize(rows,3.5,3)
    assert answer["status"]=="PROPOSED_NOT_BOOKED"
    assert answer["indicative_odds"]>=3.5
    assert len(answer["selection_ids"])==len(set(x.split(":")[0] for x in answer["selection_ids"]))
    assert answer["booking_code_created"] is False


def test_candidate_board_excludes_all_team_under_variants(monkeypatch):
    builder=types.ModuleType("leagues.builder_v2")
    rows=_examples()+[
        dict(selection_id="d:home_under_1_5",match_id="d",market="home_under_1_5",
             odds=7.2,bookable=True),
    ]
    builder.list_candidates=lambda _:{"status":"success","candidates":rows,"board":{}}
    monkeypatch.setitem(sys.modules,"leagues.builder_v2",builder)
    answer=candidate_board({"horizon":"7_days","min_trust_grade":"B"})
    assert answer["distinct_fixture_count"]==3
    assert all("under_" not in x["market"] for x in answer["candidates"])


def test_auto_booking_uses_optimizer_without_manual_ids(monkeypatch):
    import growth.private_jackpot as jackpot
    calls=[]
    monkeypatch.setattr(jackpot,"optimize_request",lambda _:{
        "status":"PROPOSED_NOT_BOOKED","selection_ids":["a:home_win","b:away_win"],
        "indicative_odds":4.1,"optimization_method":"bounded_odds_frontier",
    })
    def fake_booking(payload):
        calls.append(payload)
        return {"status":"success","share_code":"MOCKCODE","verified_odds":4.1}
    monkeypatch.setattr(jackpot,"booking_request",fake_booking)
    result=auto_booking_request({"target_odds":4.0,"horizon":"7_days"})
    assert result["share_code"]=="MOCKCODE"
    assert calls[0]["selection_ids"]==["a:home_win","b:away_win"]


def test_auto_booking_does_not_book_when_target_is_unreachable(monkeypatch):
    import growth.private_jackpot as jackpot
    monkeypatch.setattr(jackpot,"optimize_request",lambda _:{"status":"UNREACHABLE",
        "selection_ids":[],"reason":"too few matches","maximum_reference_odds":34.4})
    def no_booking(_):
        raise AssertionError("Should never book unreachable portfolio")
    monkeypatch.setattr(jackpot,"booking_request",no_booking)
    result=auto_booking_request({"target_odds":100000})
    assert result["status"]=="UNREACHABLE"
    assert result["share_code"] is None
