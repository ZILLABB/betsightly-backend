"""Official, pre-reviewed Japan J2/J3 2026-10-21 results by exact event."""
from datetime import datetime, timezone
from services.verified_incident_finals import incident_finals
from leagues.results_checker import _index_free_finals
from leagues.editorial_settlement import grade_manual_slip

CASES = [["sr:match:72151260","Jubilo Iwata","Oita Trinita","over_1_5",0,0,"lost"],["sr:match:72151252","RB Omiya Ardija","Kataller Toyama","over_1_5",0,3,"won"],["sr:match:72151254","Shonan Bellmare","Iwaki FC","over_1_5",1,1,"won"],["sr:match:72151250","Tochigi City FC","Fujieda MYFC","over_1_5",2,2,"won"],["sr:match:72151246","Vegalta Sendai","FC Imabari","home_win",3,1,"won"],["sr:match:72151256","Ventforet Kofu","Yokohama FC","over_1_5",0,3,"won"],["sr:match:72152086","Ehime FC","Renofa Yamaguchi","over_1_5",2,1,"won"],["sr:match:72152080","FC Gifu","SC Sagamihara","home_or_draw",2,1,"won"],["sr:match:72152082","FC Osaka","Nara Club","over_1_5",2,0,"won"],["sr:match:72152090","Kagoshima United","Kochi United SC","home_win",3,1,"won"]]


def test_exact_jleague_matchday_ten_final_results_are_recoverable():
    assert len(CASES) == 10
    for eid, home, away, market, hs, aw, expected in CASES:
        pick = {
            "sportybet_event_id": eid, "home_team": home,
            "away_team": away, "market": market,
            "kickoff": "2026-10-21T10:00:00Z",
            "status": "pending",
        }
        observed = incident_finals([pick])
        assert len(observed) == 1
        assert (observed[0]["home_score"], observed[0]["away_score"]) == (hs, aw)
        assert observed[0]["evidence_url"].startswith("https://www.jleague.jp/")
        record = {"games": [pick], "booking": {"share_code": "IMMUTABLE"}}
        updated = grade_manual_slip(
            record, _index_free_finals(observed),
            now=datetime(2026, 10, 28, 10, tzinfo=timezone.utc))
        assert updated["result_status"] == expected
        assert updated["booking"] == record["booking"]
        assert incident_finals([{**pick, "home_team": "Other Team"}]) == []
        assert incident_finals([{**pick, "kickoff": "2026-10-22T10:00:00Z"}]) == []
        assert incident_finals([{**pick, "sportybet_event_id": "sr:match:999999999"}]) == []
