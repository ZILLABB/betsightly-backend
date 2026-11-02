"""Free NBA games ingestion for offline BetSightly research.

No API routes, no jobs, no bookmaker calls. The free BALLDONTLIE plan requires
an API key and supports game scores, not player stats or historical odds.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.balldontlie.io/v1/games"
SOURCE = "balldontlie:nba:v1"
APPROVED_RESEARCH_SOURCES = frozenset({SOURCE, "sportsdataverse:espn_nba_schedules:v1"})
FIELDS = (
    "game_id", "date", "season", "status", "home_id", "away_id",
    "home_name", "away_name", "home_score", "away_score", "start_utc",
    "postseason", "source", "retrieved_at",
)


def normalize_game(raw: dict, retrieved_at: str | None = None) -> dict:
    """Validate and normalize one documented NBA /v1/games response."""
    if not isinstance(raw, dict):
        raise ValueError("Game must be an object")
    home, away = raw.get("home_team") or {}, raw.get("visitor_team") or {}
    when = str(raw.get("date") or "")[:10]
    date.fromisoformat(when)
    game_id = str(raw["id"]).strip()
    home_id, away_id = str(home["id"]).strip(), str(away["id"]).strip()
    if not game_id or not home_id or not away_id or home_id == away_id:
        raise ValueError("Missing, equal or invalid game/team identifiers")
    season = int(raw["season"])
    if not 1946 <= season <= 2100:
        raise ValueError("Season out of range")
    state = str(raw.get("status_state") or "").lower().strip()
    if state == "final" or (not state and str(raw.get("status", "")).lower() == "final"):
        status = "final"
    elif state in ("scheduled", "in_progress", "postponed", "canceled",
                   "delayed", "suspended", "abandoned", "unknown"):
        status = state
    else:
        status = "unknown"
    scores = (raw.get("home_team_score"), raw.get("visitor_team_score"))
    if status == "final":
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in scores):
            raise ValueError("Final game without valid scores")
        if scores[0] == scores[1]:
            raise ValueError("Basketball final has tied scores")
    else:
        scores = (None, None)
    start = raw.get("datetime")
    if start:
        # Reject malformed timestamps instead of guessing fixture timing.
        datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    return {
        "game_id": game_id, "date": when, "season": season, "status": status,
        "home_id": home_id, "away_id": away_id,
        "home_name": str(home.get("full_name") or home_id),
        "away_name": str(away.get("full_name") or away_id),
        "home_score": scores[0], "away_score": scores[1],
        "start_utc": start, "postseason": bool(raw.get("postseason", False)),
        "source": SOURCE,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
    }


def _verify_game(game: dict) -> None:
    if not isinstance(game, dict) or any(field not in game for field in FIELDS):
        raise ValueError("Invalid normalized game schema")
    if game["source"] not in APPROVED_RESEARCH_SOURCES:
        raise ValueError("Unknown historical NBA game source")
    date.fromisoformat(game["date"])
    if not game["game_id"] or not game["home_id"] or not game["away_id"]:
        raise ValueError("Invalid game identifiers")
    if game["status"] == "final":
        if not all(isinstance(game[key], int) and not isinstance(game[key], bool)
                   for key in ("home_score", "away_score")):
            raise ValueError("Final game has no scores")


def read_games(path: str | Path) -> list[dict]:
    result = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                game = json.loads(line)
                _verify_game(game)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid game at line {line_no}: {exc}") from exc
            result.append(game)
    if not result:
        raise ValueError("No verified NBA game records; refusing to train")
    ids = [g["game_id"] for g in result]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate game identifiers; refusing to train")
    return sorted(result, key=lambda g: (g["date"], g["game_id"]))


def write_games(games: list[dict], output: str | Path) -> int:
    """Atomic write: failed downloads never replace a prior valid snapshot."""
    if not games:
        raise ValueError("Refusing to write empty NBA dataset")
    unique = {}
    for game in games:
        _verify_game(game)
        old = unique.get(game["game_id"])
        if old is not None and (old["home_id"], old["away_id"], old["date"]) != (
                game["home_id"], game["away_id"], game["date"]):
            raise ValueError("Conflicting fixture IDs across pages")
        unique[game["game_id"]] = game
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=target.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            for game in sorted(unique.values(), key=lambda g: (g["date"], g["game_id"])):
                stream.write(json.dumps(game, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return len(unique)


def fetch_seasons(seasons: list[int], api_key: str, max_pages: int = 1000,
                  pause_seconds: float = 13.0) -> list[dict]:
    """Paginate BALLDONTLIE seasons; fail closed on interrupted fetch.

    Rate-limited conservatively for free plans (5 req/min).
    max_pages is a safety ceiling; reaching it is a failure, not success.
    """
    if not api_key.strip():
        raise ValueError("Set BALLDONTLIE_API_KEY in the local environment")
    if not seasons or max_pages <= 0 or pause_seconds < 12.0:
        raise ValueError("Seasons, page ceiling and free-plan rate limit required")
    combined, request_count = {}, 0
    for season in sorted(set(seasons)):
        if not 1946 <= season <= date.today().year:
            raise ValueError(f"Invalid season {season}")
        cursor, seen_cursors = None, set()
        for page in range(max_pages):
            if request_count:
                time.sleep(pause_seconds)
            params = [("per_page", 100), ("seasons[]", season),
                      ("season_type", "regular")]
            if cursor is not None:
                params.append(("cursor", cursor))
            url = f"{API_URL}?{urlencode(params)}"
            request = Request(url, headers={
                "Authorization": api_key,
                "Accept": "application/json",
                "User-Agent": "BetSightlyResearch/1.0",
            })
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.load(response)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"NBA download failed for season {season}: {exc}") from exc
            request_count += 1
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Invalid NBA provider payload")
            for raw in payload["data"]:
                game = normalize_game(raw)
                if game["season"] != season or game["postseason"]:
                    continue
                old = combined.get(game["game_id"])
                if old is not None and (old["date"], old["home_id"], old["away_id"]) != (
                        game["date"], game["home_id"], game["away_id"]):
                    raise ValueError("Conflicting NBA game identity")
                combined[game["game_id"]] = game
            next_cursor = (payload.get("meta") or {}).get("next_cursor")
            if next_cursor is None:
                break
            if str(next_cursor) in seen_cursors:
                raise ValueError("NBA pagination cursor repeated")
            seen_cursors.add(str(next_cursor))
            cursor = next_cursor
        else:
            raise RuntimeError(f"NBA pagination exceeded {max_pages} pages for {season}")
    if not combined:
        raise ValueError("NBA provider returned no games")
    return list(combined.values())
