"""Grouped NBA market desk contract: all games, no model-picked betting line."""
from datetime import datetime, timedelta, timezone

from basketball.research_market_presentation import present_market_snapshot
from basketball.research_market_watch import _event, match_board
from tests.test_basketball_market_watch import bookmaker, fixture, NOW


def test_all_matched_games_visible_even_after_first_120_alt_lines():
    archived = []
    forecast_games = []
    for idx in range(9):
        g = fixture()
        g["game_id"] = str(401909870 + idx)
        g["start_utc"] = (NOW + timedelta(hours=8+idx)).isoformat()
        event = bookmaker()
        event["eventId"] = "sr:match:" + str(123456789 + idx)
        event["estimateStartTime"] = int(
            (NOW + timedelta(hours=8+idx)).timestamp()*1000)
        event["markets"] = [
            {"id":"225","specifier":f"total={210.5+j}",
             "outcomes":[{"id":"12","odds":1.8+j*.002},
                         {"id":"13","odds":1.92-j*.001}]}
            for j in range(25)
        ]
        archived.extend(match_board([g],[_event(event,competition="NBA")],now=NOW))
        forecast_games.append({
            "game_id":g["game_id"],"advanced_total":231.5,
            "projected_total":230.0,"status":"upcoming"})
    report = present_market_snapshot(
        {"games":forecast_games},
        {"fixtures":archived,"observed_at":NOW.isoformat(),
         "digest":"synthetic-only","source":"sportybet_ng_basketball_read_only"}
    )
    assert report["fixture_matches"] == 9
    assert len(report["reference_games"]) == 9
    assert report["available_line_count"] == 9*25
    assert len(report["quoted_totals"]) == 9*25
    assert report["display_truncated"] is False
    assert all(r["available_lines"] == 25 for r in report["reference_games"])
    assert all(r["recommendation"] == "NO_SELECTION_UNCALIBRATED"
               for r in report["reference_games"])
    assert report["calibrated_betting_edge"] is False


def test_reference_is_median_of_offered_ladder_not_prediction_driven():
    g = fixture()
    event = bookmaker()
    event["markets"] = [
        {"id":"225","specifier":f"total={230.5+j}",
         "outcomes":[{"id":"12","odds":1.8},
                     {"id":"13","odds":1.9}]}
        for j in range(5)
    ]
    matches = match_board([g],[_event(event,competition="NBA")],now=NOW)
    receipt = {"fixtures":matches,"observed_at":NOW.isoformat(),
               "digest":"synthetic-only",
               "source":"sportybet_ng_basketball_read_only"}
    a = present_market_snapshot({"games":[{
         "game_id":g["game_id"],"advanced_total":260.0,
         "status":"upcoming"}]},receipt)
    b = present_market_snapshot({"games":[{
         "game_id":g["game_id"],"advanced_total":190.0,
         "status":"upcoming"}]},receipt)
    assert a["reference_games"][0]["reference_total"] == 232.5
    assert b["reference_games"][0]["reference_total"] == 232.5
    assert a["reference_games"][0]["paper_direction"] == "over"
    assert b["reference_games"][0]["paper_direction"] == "under"
