"""Public SportsDataverse/hoopR NBA schedules for private offline research.

These release assets require no API key. ESPN-derived data may carry additional
rights restrictions; this research integration DOES NOT authorize commercial
republication, gambling use or redistribution of raw provider data.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from basketball.research_data import _verify_game

SOURCE = "sportsdataverse:espn_nba_schedules:v1"
RELEASE = (
    "https://github.com/sportsdataverse/sportsdataverse-data/"
    "releases/download/espn_nba_schedules/nba_schedule_{season}.csv"
)
MAX_SEASON_BYTES = 20_000_000
DEFAULT_SEASONS = tuple(range(2017, 2028))
REQUIRED = frozenset({
    "game_id", "game_date", "season", "season_type", "home_id", "away_id",
    "home_score", "away_score", "status_type_completed",
    "status_type_name", "home_display_name", "away_display_name",
})


def _int_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text.isdecimal() or int(text) <= 0:
        raise ValueError("Missing or nonnumeric ESPN team/game ID")
    return str(int(text))


def _utc_datetime(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Invalid ESPN game start timestamp") from exc
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("ESPN start time must have timezone")
    return ts.astimezone(timezone.utc).isoformat()


def normalize_schedule_row(raw: dict, requested_season: int,
                           retrieved_at: str) -> dict | None:
    """Normalize one ESPN schedule row; skip non-regular-season games."""
    if str(raw.get("season_type", "")).strip() != "2":
        return None
    # Some source schedules include TBA/postponed placeholders without team IDs.
    # Exclude rather than invent an opponent, and report rejection totals.
    identifiers = [str(raw.get(key) or "").strip()
                   for key in ("game_id", "home_id", "away_id")]
    if not all(value.isdecimal() and int(value) > 0 for value in identifiers):
        return None
    season = int(raw["season"])
    if season != requested_season:
        raise ValueError("Season mismatch in ESPN schedule asset")
    day = (raw.get("game_date") or "").strip()
    if not day:
        day = str(raw.get("date") or "")[:10]
    date.fromisoformat(day)
    status_name = str(raw.get("status_type_name") or "").upper().strip()
    complete = str(raw.get("status_type_completed") or "").upper().strip() == "TRUE"
    if complete and status_name == "STATUS_FINAL":
        status = "final"
        home_score, away_score = int(raw["home_score"]), int(raw["away_score"])
        if min(home_score, away_score) < 0 or home_score == away_score:
            raise ValueError("Invalid final NBA basketball score")
    elif complete:
        status = "canceled"
        home_score = away_score = None
    else:
        status = "scheduled" if status_name in (
            "STATUS_SCHEDULED", "STATUS_PRE", "STATUS_PREGAME",
        ) else "unknown"
        home_score = away_score = None
    game = {
        "game_id": _int_id(raw.get("game_id")),
        "date": day, "season": season, "status": status,
        "home_id": _int_id(raw.get("home_id")),
        "away_id": _int_id(raw.get("away_id")),
        "home_name": str(raw.get("home_display_name") or "").strip(),
        "away_name": str(raw.get("away_display_name") or "").strip(),
        "home_score": home_score, "away_score": away_score,
        "start_utc": _utc_datetime(raw.get("game_date_time") or raw.get("date")),
        "postseason": False, "source": SOURCE, "retrieved_at": retrieved_at,
    }
    if not game["home_name"] or not game["away_name"]:
        raise ValueError("Missing team display names")
    _verify_game(game)
    return game


def read_release_csv(data: bytes, season: int, retrieved_at: str | None = None) -> list[dict]:
    """Validate CSV header, provenance fields and schedule identities."""
    if len(data) > MAX_SEASON_BYTES:
        raise ValueError("NBA season CSV exceeds safety limit")
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat()
    decoded = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames or not REQUIRED.issubset(set(reader.fieldnames)):
        raise ValueError("NBA schedule CSV missing required columns")
    games = {}
    row_count = 0
    rejected_regular = 0
    for row in reader:
        row_count += 1
        parsed = normalize_schedule_row(row, season, timestamp)
        if parsed is None:
            if str(row.get("season_type", "")).strip() == "2":
                rejected_regular += 1
            continue
        before = games.get(parsed["game_id"])
        if before is not None:
            identifying = ("date", "home_id", "away_id", "season")
            if any(before[k] != parsed[k] for k in identifying):
                raise ValueError("Conflicting schedule fixture identity")
            if before["status"] == "final" and parsed["status"] == "final":
                if (before["home_score"], before["away_score"]) != (
                        parsed["home_score"], parsed["away_score"]):
                    raise ValueError("Conflicting completed scores for same fixture")
            if parsed["status"] == "final":
                games[parsed["game_id"]] = parsed
        else:
            games[parsed["game_id"]] = parsed
    if row_count < 500 or len(games) < 400:
        raise ValueError(f"Implausibly incomplete NBA season: {len(games)} games")
    if rejected_regular > max(5, round(0.01 * len(games))):
        raise ValueError(
            f"NBA season {season} has {rejected_regular} invalid regular-season "
            f"fixtures; exceeds 1% identity coverage budget")
    if rejected_regular:
        print(f"NBA season {season}: excluded {rejected_regular} unidentifiable "
              "regular-season rows (no invented identities)", flush=True)
    return list(games.values())


def fetch_public_seasons(seasons: list[int], timeout: int = 90) -> tuple[list[dict], list[dict]]:
    """Download verified free public schedule assets with strong diagnostics.

    Each file is capped at 20 MB. An interrupted/incomplete season aborts the
    batch; caller writes the combined snapshot only after all seasons succeed.
    """
    if not seasons or any(y < 2002 or y > date.today().year + 1 for y in seasons):
        raise ValueError("Invalid ESPN season years")
    merged, provenance = {}, []
    for season in sorted(set(seasons)):
        url = RELEASE.format(season=season)
        request = Request(url, headers={
            "User-Agent": "BetSightlyNBAResearch/1.0",
            "Accept": "text/csv,application/octet-stream;q=0.9",
        })
        try:
            with urlopen(request, timeout=timeout) as response:
                if int(response.headers.get("Content-Length") or 0) > MAX_SEASON_BYTES:
                    raise ValueError("NBA schedule asset size is excessive")
                raw = response.read(MAX_SEASON_BYTES + 1)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"Public NBA season {season} unavailable: {exc}") from exc
        games = read_release_csv(raw, season)
        for g in games:
            prior = merged.get(g["game_id"])
            if prior and (prior["date"], prior["home_id"], prior["away_id"]) != (
                    g["date"], g["home_id"], g["away_id"]):
                raise ValueError("Conflicting game IDs across seasonal files")
            merged[g["game_id"]] = g
        provenance.append({
            "season": season, "source_url": url,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "regular_season_games": len(games),
            "final_games": sum(g["status"] == "final" for g in games),
        })
    return list(merged.values()), provenance
