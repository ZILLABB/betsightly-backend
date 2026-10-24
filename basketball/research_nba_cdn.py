"""Independent keyless official NBA live CDN final-score verification.

The NBA CDN uses different game/team IDs from ESPN schedules. Accept final
scores ONLY after an exact unique team-tricode match, provider-local date
match and near-identical UTC tipoff. Never infer a score by team name alone.
This feed supplies the NBA's current scoreboard, NOT arbitrary past dates.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from basketball.research_scoreboard import _fetch_json, _utc

NBA_CDN_SOURCE = "nba:official_live_cdn:scoreboard:v1"
NBA_CDN_URL = (
    "https://cdn.nba.com/static/json/liveData/scoreboard/"
    "todaysScoreboard_00.json"
)

# Explicit human-verified full-name to official NBA tricode mapping; strict,
# never fuzzy match player names, team nicknames, home/away or unknown teams.
NBA_TEAM_CODES = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def _final_score(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Official NBA final has invalid score")
    return value


def _official_games(payload: dict, requested_day: str) -> list[dict]:
    date.fromisoformat(requested_day)
    scoreboard = payload.get("scoreboard")
    if not isinstance(scoreboard, dict):
        raise RuntimeError("NBA_CDN_MISSING_SCOREBOARD")
    if scoreboard.get("gameDate") != requested_day:
        raise RuntimeError("NBA_CDN_DATE_MISMATCH")
    if scoreboard.get("leagueId") != "00":
        raise RuntimeError("NBA_CDN_WRONG_LEAGUE")
    games = scoreboard.get("games")
    if not isinstance(games, list) or len(games) > 50:
        raise RuntimeError("NBA_CDN_INVALID_GAMES")
    return games


def match_nba_cdn_finals(
    payload: dict, requested_day: str, fixtures: list[dict],
    *, retrieved_at: str,
) -> dict[str, dict]:
    """Convert final NBA live scoreboard games to uniquely matched ESPN IDs.

    Home/away tricodes, fixture date, kickoff within 30 minutes and unique
    candidate are ALL required. The original NBA ID remains in provenance.
    """
    scoreboard_games = _official_games(payload, requested_day)
    by_pair = defaultdict(list)
    for game in fixtures:
        if game["date"] != requested_day or game.get("postseason"):
            continue
        home_code = NBA_TEAM_CODES.get(game.get("home_name"))
        away_code = NBA_TEAM_CODES.get(game.get("away_name"))
        if home_code and away_code and home_code != away_code:
            by_pair[(home_code, away_code)].append(game)
    results = {}
    mapped_nba_ids = set()
    for nba in scoreboard_games:
        if not isinstance(nba, dict) or nba.get("gameStatus") != 3:
            continue
        status_text = str(nba.get("gameStatusText") or "")
        if not (status_text == "Final" or status_text.startswith("Final/")):
            continue
        home = nba.get("homeTeam") or {}
        away = nba.get("awayTeam") or {}
        home_code = str(home.get("teamTricode") or "")
        away_code = str(away.get("teamTricode") or "")
        ident = str(nba.get("gameId") or "")
        if (not ident.isdecimal() or len(ident) != 10 or
                not home_code or not away_code or home_code == away_code):
            raise ValueError("Invalid official NBA final identity")
        if ident in mapped_nba_ids:
            raise ValueError("Duplicate official NBA game ID")
        candidates = by_pair.get((home_code, away_code), [])
        nba_start = _utc(nba.get("gameTimeUTC"))
        if nba_start is None:
            raise ValueError("Official NBA final missing UTC start")
        matches = [
            game for game in candidates
            if _utc(game.get("start_utc")) is not None and
            abs((_utc(game["start_utc"]) - nba_start).total_seconds()) <= 1800
        ]
        if len(matches) > 1:
            raise ValueError("Ambiguous official NBA cross-provider match")
        if not matches:
            continue  # Do not guess or create an ESPN identity.
        game = matches[0]
        if game["game_id"] in results:
            raise ValueError("Duplicated mapped official NBA result")
        hs = _final_score(home.get("score"))
        vs = _final_score(away.get("score"))
        if hs == vs:
            raise ValueError("NBA official final score cannot be tied")
        results[str(game["game_id"])] = {
            "game_id": str(game["game_id"]),
            "home_id": str(game["home_id"]),
            "away_id": str(game["away_id"]),
            "home_score": hs, "away_score": vs,
            "start_utc": nba_start.isoformat(),
            "retrieved_at": retrieved_at,
            "source": NBA_CDN_SOURCE,
            "provider_game_id": ident,
        }
        mapped_nba_ids.add(ident)
    return results


def download_nba_cdn(requested_day: str, *, timeout: int = 15) -> dict:
    """Return only the NBA server's genuine current local-day scoreboard."""
    payload = _fetch_json(NBA_CDN_URL, expected_host="cdn.nba.com",
                          timeout=timeout)
    _official_games(payload, requested_day)
    return payload
