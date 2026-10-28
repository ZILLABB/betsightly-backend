"""Read-only, bounded EuroLeague / EuroCup *candidate evidence*.

Euroleague v2 competition games endpoint is public-facing but not a license
for redistribution, sportsbook settlement, model training, or publication.
Nothing in this file stores NBA data, creates bets, or changes release gates.
"""
from __future__ import annotations

EUROPE = {"euroleague": "E", "eurocup": "U"}
BASE_URL = "https://api-live.euroleague.net/v2/competitions"
MAX_SEASON_GAMES = 750
MAX_RESPONSE_BYTES = 2_000_000


def source_url(league: str, start_year: int) -> str:
    if (league not in EUROPE or type(start_year) is not int
            or not 2000 <= start_year <= 2035):
        raise ValueError("EUROPE_LEAGUE_OR_SEASON_NOT_SUPPORTED")
    code = EUROPE[league]
    return f"{BASE_URL}/{code}/seasons/{code}{start_year}/games"


def audit_season_response(league: str, start_year: int, body: dict) -> dict:
    """Inspect identities/count only; no implied finalized-score agreement."""
    source_url(league, start_year)
    if not isinstance(body, dict) or type(body.get("total")) is not int:
        raise ValueError("EUROPE_PROVIDER_ENVELOPE_INVALID")
    total, games = body["total"], body.get("data")
    if (not 0 <= total <= MAX_SEASON_GAMES or not isinstance(games, list)
            or len(games) > MAX_SEASON_GAMES or len(games) > total):
        raise ValueError("EUROPE_PROVIDER_COUNT_INVALID")
    identities = set()
    for game in games:
        if not isinstance(game, dict):
            raise ValueError("EUROPE_PROVIDER_GAME_INVALID")
        # Keep identifiers opaque. This is not a team/period/score normalizer.
        identifier = game.get("id") or game.get("identifier") or game.get("gameCode")
        if (type(identifier) not in (int, str) or not str(identifier).strip()
                or len(str(identifier)) > 128 or str(identifier) in identities):
            raise ValueError("EUROPE_PROVIDER_IDENTITY_INVALID")
        identities.add(str(identifier))
    return {
        "league": league,
        "season_code": EUROPE[league] + str(start_year),
        "source": "euroleague_v2_public_candidate",
        "season_total_claimed": total,
        "page_identities_checked": len(games),
        "page_complete": len(games) == total,
        "status": "source_candidate_not_validated",
        "research_only": True,
        "not_bookable": True,
        "approved_for_training": False,
        "approved_for_settlement": False,
        "approved_for_public_predictions": False,
        "license_cleared": False,
        "cross_source_finals_verified": False,
        "reason": "Missing independent score, club identity, season and rights acceptance.",
    }


def probe_season(league: str, start_year: int, *, get=None) -> dict:
    """At most one read; no automatic scraping, retries or writes."""
    import requests
    caller = get or requests.get
    url = source_url(league, start_year)
    response = caller(
        url, timeout=12, allow_redirects=False,
        headers={"Accept": "application/json"},
    )
    if response.status_code != 200:
        raise ValueError("EUROPE_PROVIDER_UNAVAILABLE")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("EUROPE_PROVIDER_TOO_LARGE")
    try:
        body = response.json()
    except ValueError as exc:
        raise ValueError("EUROPE_PROVIDER_INVALID_JSON") from exc
    return audit_season_response(league, start_year, body)
