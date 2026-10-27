"""League inventory must never reclassify other sports as trained NBA data."""
from growth.basketball_coverage import summarize, MODEL_READINESS


def test_exact_available_leagues_without_fabricated_roster():
    report=summarize({"status":"success","fetched_at":1793112000,
      "fixtures":[
        {"competition":"NBA","home_team":"Boston Celtics","away_team":"New York Knicks",
         "markets":[{"market_id":"219"}]},
        {"competition":"NBA","home_team":"Brooklyn Nets","away_team":"Boston Celtics",
         "markets":[{"market_id":"225"}]},
        {"competition":"Euroleague","home_team":"Olympiacos","away_team":"Fenerbahce",
         "markets":[{"market_id":"219"}]},
        {"competition":"WNBA","home_team":"Aces","away_team":"Liberty","markets":[]},
      ]})
    assert report["total_games"] == 4
    assert len(report["leagues"]) == 3
    assert report["market_counts"] == {"219":2,"225":1}
    assert report["leagues"][0]["name"] == "NBA"
    assert report["leagues"][0]["model_status"] == "private_nba_research"
    assert all(item["model_status"] == "bookmaker_only"
               for item in report["leagues"] if item["name"] != "NBA")
    assert "Olympiacos" in report["teams"]


def test_missing_board_does_not_claim_fixture_inventory():
    result=summarize({"status":"BOARD_REFRESH_REQUIRED","fixtures":[
      {"competition":"Euroleague","home_team":"x","away_team":"y"}]})
    assert result["status"] == "unavailable"
    assert result["leagues"] == []


def test_non_nba_and_player_research_not_published():
    for key in ("wnba","ncaa","euroleague","other_leagues","nba_player_props"):
        assert MODEL_READINESS[key]["state"] in ("no_approved_forecasts","not_validated")
    assert MODEL_READINESS["nba_moneyline"]["state"]=="paper_research"
