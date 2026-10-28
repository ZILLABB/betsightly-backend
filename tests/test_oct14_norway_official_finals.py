"""Norwegian OBOS-ligaen 14 Oct source-confirmed finals, exact bookmaker ID."""
from datetime import datetime, timezone
from leagues.editorial_settlement import grade_manual_slip
from leagues.results_checker import _index_free_finals
from services.verified_incident_finals import incident_finals

CASES = [
    ("sr:match:67018238", "Stroemmen IF", "Aasane Fotball", 6, 1, "over_1_5", "won"),
    ("sr:match:67018228", "FK Haugesund", "Lyn 1896 FK", 3, 0, "home_win", "won"),
    ("sr:match:67018236", "Stabaek IF", "Sandnes Ulf", 4, 1, "over_2_5", "won"),
    ("sr:match:67018232", "Moss FK", "Egersunds IK", 0, 0, "over_1_5", "lost"),
    ("sr:match:67018230", "Hoedd IL", "Ranheim", 1, 1, "over_2_5", "lost"),
    ("sr:match:67018240", "Stroemsgodset IF", "Kongsvinger IL Toppfotball", 5, 1, "over_2_5", "won"),
    ("sr:match:67018234", "Sogndal Fotball", "Odds BK", 0, 1, "over_2_5", "lost"),
    ("sr:match:67018226", "Bryne FK", "Raufoss IL", 1, 1, "home_win", "lost"),
]


def test_eight_norwegian_90min_receipts_grade_and_never_cross_events():
    assert len(CASES) == 8
    for eid, home, away, hs, aw, market, expected in CASES:
        game = {
            "sportybet_event_id": eid, "home_team": home,
            "away_team": away, "kickoff": "2026-10-14T17:00:00Z",
            "market": market, "status": "pending",
        }
        source = incident_finals([game])
        assert len(source) == 1
        assert (source[0]["home_score"], source[0]["away_score"]) == (hs, aw)
        assert source[0]["evidence_url"] == "https://www.obos-ligaen.no/resultater"
        slip = {"games": [game], "booking": {"share_code": "UNCHANGED"}}
        result = grade_manual_slip(
            slip, _index_free_finals(source),
            now=datetime(2026, 10, 28, 11, tzinfo=timezone.utc))
        assert result["result_status"] == expected
        assert result["booking"] == slip["booking"]
        assert incident_finals([{**game, "sportybet_event_id": "sr:match:1234"}]) == []
        assert incident_finals([{**game, "away_team": "Wrong Club"}]) == []
        assert incident_finals([{**game, "kickoff": "2026-10-15T17:00:00Z"}]) == []
