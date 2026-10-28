"""Read-only European basketball final-score adapter for private settlement.

Uses the competition organiser's public game feed. A scoreboard event is not a
verified final unless played=True and both complete scores are present.
No bookmaker selections, predictions, or research snapshots are modified here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import re
import unicodedata

BASE = "https://api-live.euroleague.net/v2/competitions"
COMPETITIONS = {"EUROLEAGUE": "E", "EUROCUP": "U"}
SOURCE = "EUROLEAGUE_OFFICIAL_FINAL"

# Explicit, competition-specific names; never use a fuzzy similarity threshold
# to decide a real-money ticket. Sponsorship aliases are deliberately bounded.
_ALIASES = {
    "hapoelibitelaviv": "hapoeltelaviv",
    "hapoelshlomotelaviv": "hapoeltelaviv",
    "hapoeltelaviv": "hapoeltelaviv",
    "anadoluefesistanbul": "anadoluefes",
    "anadoluefessk": "anadoluefes",
    "anadoluefes": "anadoluefes",
    "arismideathessaloniki": "aristhessaloniki",
    "aristhessaloniki": "aristhessaloniki",
    "cedevitaolimpijaliubljana": "cedevitaolimpijaljubljana",
    "partizanmozzartbetbelgrade": "partizanbelgrade",
    "partizanbelgrade": "partizanbelgrade",
    "ldlcasvelvilleurbanne": "asvelvilleurbanne",
    "asvellyonvilleurbanne": "asvelvilleurbanne",
    "asvelvilleurbanne": "asvelvilleurbanne",
    "virtussegafredobologna": "virtusbologna",
    "virtusbologna": "virtusbologna",
    "hapoelmidtownjerusalem": "hapoeljerusalem",
    "hapoeljerusalem": "hapoeljerusalem",
    "lemanssarthebasket": "lemans",
    "lemans": "lemans",
    "zalgiriskaunas": "zalgiriskaunas",
    "neptunasklaipeda": "neptunasklaipeda",
    "napolibasket": "napolibasket",
    "slaskwroclaw": "slaskwroclaw",
    "tofasbursa": "tofasbursa",
    "tofasskbursa": "tofasbursa",
    "derthonabasket": "derthonabasket",
    "rostockseawolves": "rostockseawolves",
}


def identity(name):
    plain = unicodedata.normalize("NFKD", str(name or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = re.sub(r"[^a-z0-9]", "", plain.lower())
    for prefix in ("bc", "kk", "sk", "wks"):
        if plain.startswith(prefix) and len(plain) > len(prefix) + 6:
            plain = plain[len(prefix):]
            break
    return _ALIASES.get(plain, plain)


def _club_names(side):
    club = side.get("club") if isinstance(side, dict) else None
    if not isinstance(club, dict):
        return []
    return [club[k] for k in (
        "name", "editorialName", "abbreviatedName", "clubPermanentName"
    ) if isinstance(club.get(k), str) and club[k].strip()]


def parse_final(raw, competition, season):
    if not isinstance(raw, dict) or raw.get("played") is not True:
        return None
    state = str(raw.get("gameStatus") or "").strip().lower()
    if state and state not in {"played", "finished", "final", "completed", "ended", "closed"}:
        return None
    local, road = raw.get("local"), raw.get("road")
    home_names, away_names = _club_names(local), _club_names(road)
    if not home_names or not away_names:
        return None
    try:
        h, a = local["score"], road["score"]
        if type(h) is not int or type(a) is not int or not 0 <= h <= 250 or not 0 <= a <= 250:
            return None
        code = int(raw["gameCode"])
        if code <= 0 or str(raw["gameCode"]) != str(code):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    date_raw = raw.get("date")
    if not isinstance(date_raw, str) or not date_raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        dated_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_raw))
        if parsed.tzinfo is None and not dated_only:
            return None  # A naive local time is not safe to match to UTC
        tipoff = parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        day = date.fromisoformat(date_raw[:10])
    except (TypeError, ValueError):
        return None
    return {
        "source": SOURCE, "source_event_id": f"{season}:{code}",
        "competition": competition, "home_names": home_names,
        "away_names": away_names, "home_score": h, "away_score": a,
        "tipoff": tipoff, "calendar_day": day, "date_only": dated_only,
    }


def fetch_finals(competition, season_year, *, get=None):
    import requests
    kind = COMPETITIONS.get(str(competition).strip().upper())
    if kind is None or not isinstance(season_year, int) or not 2000 <= season_year <= 2100:
        raise ValueError("Unsupported European basketball competition or season")
    season = f"{kind}{season_year}"
    url = f"{BASE}/{kind}/seasons/{season}/games"
    response = (get or requests.get)(url, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Invalid European season results envelope")
    games = payload["data"]
    if len(games) > 550:
        raise ValueError("Oversized European season results envelope")
    return [result for raw in games
            if (result := parse_final(raw, kind, season)) is not None]


def match_final(leg, events):
    """Must agree on competition, both teams, kickoff and unique game id."""
    comp = COMPETITIONS.get(str(leg.get("competition") or "").strip().upper())
    if not comp:
        return None
    try:
        kickoff = datetime.fromtimestamp(int(leg["kickoff_ms"]) / 1000, tz=timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    home, away = identity(leg.get("home_team")), identity(leg.get("away_team"))
    if not home or not away or home == away:
        return None
    matched = []
    for event in events:
        if event["competition"] != comp:
            continue
        if home not in {identity(n) for n in event["home_names"]}:
            continue
        if away not in {identity(n) for n in event["away_names"]}:
            continue
        if event["tipoff"] is not None:
            if abs((event["tipoff"] - kickoff).total_seconds()) > 4 * 3600:
                continue
        elif abs((event["calendar_day"] - kickoff.date()).days) > 1:
            continue
        matched.append(event)
    unique = {e["source_event_id"]: e for e in matched}
    return next(iter(unique.values())) if len(unique) == 1 else None
