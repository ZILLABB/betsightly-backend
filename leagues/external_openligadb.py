"""Opt-in, read-only OpenLigaDB source pilot for BetSightly external evidence.

OpenLigaDB is a community-maintained source, NOT verified scoring authority.
Its API data is ODbL-licensed; provenance/attribution must stay attached.
This module does not modify forecasts, sportsbook bookings or settlement.

Network fetching is disabled unless BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED=true.
Fixtures remain provider-local until Batch 3 canonical identity reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from leagues.jev_evidence_contract import _utc, _iso

logger = logging.getLogger(__name__)
SOURCE_ID = "openligadb"
SOURCE_ORIGIN = "https://api.openligadb.de"
ATTRIBUTION = "OpenLigaDB community contributors (ODbL); https://www.openligadb.de/"
ALLOWED_LEAGUES = frozenset({"bl1", "bl2", "bl3"})
MAX_BODY_BYTES = 512 * 1024
MAX_MATCHES = 46
CACHE_TTL_SECONDS = 30 * 60
_TIMEOUT_SECONDS = 8
_CACHE: dict[tuple[str, int, int], tuple[float, dict]] = {}
_LOCK = threading.Lock()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def enabled(environ: dict[str, str] | None = None) -> bool:
    config = os.environ if environ is None else environ
    return str(config.get("BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED", "")).strip().lower() in {
        "yes", "true", "1",
    }


def source_url(league: str, season: int, matchday: int) -> str:
    """Use only a pinned HTTPS host and explicitly approved competition codes."""
    if league not in ALLOWED_LEAGUES:
        raise ValueError("unsupported OpenLigaDB league")
    if type(season) is not int or not 2000 <= season <= datetime.now(timezone.utc).year + 1:
        raise ValueError("invalid league season")
    if type(matchday) is not int or not 1 <= matchday <= 46:
        raise ValueError("invalid matchday")
    return f"{SOURCE_ORIGIN}/getmatchdata/{league}/{season}/{matchday}"


def _read_json(url: str) -> Any:
    """HTTP GET with a bounded response, timeout and redirects disabled."""
    if not url.startswith(f"{SOURCE_ORIGIN}/getmatchdata/"):
        raise ValueError("unapproved API URL")
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "BetSightlyEvidencePilot/0.1 (+https://betsightly.com)",
    })
    with build_opener(_NoRedirect()).open(req, timeout=_TIMEOUT_SECONDS) as res:
        content_type = (res.headers.get("Content-Type") or "").lower()
        if "json" not in content_type:
            raise ValueError("non-JSON source response")
        blob = res.read(MAX_BODY_BYTES + 1)
        if len(blob) > MAX_BODY_BYTES:
            raise ValueError("source response exceeds byte cap")
        return json.loads(blob)


def _full_time_result(row: dict) -> dict | None:
    """OpenLigaDB exposes halftime and full-time results in one array."""
    if row.get("matchIsFinished") is not True:
        return None
    results = row.get("matchResults")
    if not isinstance(results, list):
        return None
    finals = [item for item in results if isinstance(item, dict)
              and item.get("resultTypeID") == 2]
    if len(finals) != 1:
        return None
    final = finals[0]
    home, away = final.get("pointsTeam1"), final.get("pointsTeam2")
    if (type(home) is not int or type(away) is not int or
            not (0 <= home <= 99 and 0 <= away <= 99)):
        return None
    return {"home": home, "away": away}


def normalize_matchday(
    raw: Any, *, league: str, season: int, matchday: int,
    captured_at: datetime, as_of: datetime | None = None,
) -> dict[str, Any]:
    """Normalize a *captured* snapshot without fabricating an ESPN fixture ID.

    A snapshot obtained after a historical as-of time cannot be replayed as
    if it existed before that time. Pre-kickoff / pre-as-of claims are checked
    again by the Jev envelope adapter in Batch 3.
    """
    url = source_url(league, season, matchday)
    seen_at = _utc(captured_at)
    cutoff = _utc(as_of or captured_at)
    if seen_at is None or cutoff is None:
        raise ValueError("timestamps must include a timezone")
    if seen_at > cutoff:
        raise ValueError("cannot backdate evidence from a later source fetch")
    if not isinstance(raw, list) or len(raw) > MAX_MATCHES:
        raise ValueError("invalid or unexpectedly large matchday")
    fixtures: list[dict] = []
    evidence: list[dict] = []
    rejected: dict[str, int] = {}
    seen_ids: set[int] = set()

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for item in raw:
        if not isinstance(item, dict):
            reject("malformed_match")
            continue
        match_id = item.get("matchID")
        home = item.get("team1")
        away = item.get("team2")
        kickoff = _utc(item.get("matchDateTimeUTC"))
        if (type(match_id) is not int or match_id <= 0 or
                not isinstance(home, dict) or not isinstance(away, dict) or
                not str(home.get("teamName") or "").strip() or
                not str(away.get("teamName") or "").strip() or
                kickoff is None):
            reject("missing_match_identity")
            continue
        if item.get("leagueShortcut") not in (None, league):
            reject("league_mismatch")
            continue
        if item.get("leagueSeason") not in (None, season):
            reject("season_mismatch")
            continue
        if match_id in seen_ids:
            reject("duplicate_provider_match_id")
            continue
        seen_ids.add(match_id)
        h = str(home["teamName"]).strip()[:160]
        a = str(away["teamName"]).strip()[:160]
        match_url = f"{SOURCE_ORIGIN}/getmatchdata/{match_id}"
        full_time = _full_time_result(item) if kickoff <= seen_at else None
        row = {
            "sport": "football",
            "source_id": SOURCE_ID,
            "provider_match_id": str(match_id),
            "league_shortcut": league,
            "league_season": season,
            "matchday": matchday,
            "home_team": h,
            "away_team": a,
            "kickoff_utc": _iso(kickoff),
            "observed_at": _iso(seen_at),
            "source_url": match_url,
            "source_attribution": ATTRIBUTION,
            "reported_finished": bool(item.get("matchIsFinished")),
            "reported_full_time": full_time,
            "provider_identity_verified_to_espn": False,
            "eligible_for_automatic_settlement": False,
        }
        fixtures.append(row)
        if kickoff > cutoff:
            kind = "competition_schedule"
            claim = f"OpenLigaDB reports upcoming fixture: {h} vs {a} at {_iso(kickoff)}"
        elif full_time is not None:
            kind = "recent_results"
            claim = (f"OpenLigaDB community-reported full-time: {h} "
                     f"{full_time['home']}-{full_time['away']} {a}")
        else:
            # Never report an in-progress score as a completed result.
            continue
        evidence.append({
            "type": kind,
            "source_id": f"openligadb:{league}:{match_id}",
            "source_url": match_url,
            "observed_at": _iso(seen_at),
            "claim": claim,
        })
    return {
        "status": "ok",
        "source_id": SOURCE_ID,
        "source_url": url,
        "attribution": ATTRIBUTION,
        "license": "ODbL",
        "captured_at": _iso(seen_at),
        "provider_identity_verified_to_espn": False,
        "eligible_for_automatic_settlement": False,
        "fixtures": fixtures,
        "evidence": evidence,
        "rejected": rejected,
    }


def fetch_matchday(
    league: str, season: int, matchday: int, *,
    environ: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Explicit-only one-matchday ingestion; does not run on web requests."""
    url = source_url(league, season, matchday)
    if not enabled(environ):
        return {"status": "disabled", "source_id": SOURCE_ID, "url": url,
                "network_called": False, "publication_changed": False}
    current = _utc(now or datetime.now(timezone.utc))
    if current is None:
        raise ValueError("now must be aware")
    key = (league, season, matchday)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return {**cached[1], "cache_hit": True}
    try:
        raw = _read_json(url)
        result = normalize_matchday(
            raw, league=league, season=season, matchday=matchday,
            captured_at=current)
    except HTTPError as exc:
        logger.warning("OpenLigaDB HTTP failure: status=%s", exc.code)
        return {"status": "rate_limited" if exc.code == 429 else "unavailable",
                "reason": "http_error", "http_status": exc.code,
                "source_id": SOURCE_ID, "publication_changed": False}
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("OpenLigaDB source failed: %s", type(exc).__name__)
        return {"status": "unavailable", "reason": type(exc).__name__,
                "source_id": SOURCE_ID, "publication_changed": False}
    with _LOCK:
        _CACHE[key] = (time.monotonic(), result)
        while len(_CACHE) > 32:
            _CACHE.pop(next(iter(_CACHE)))
    return {**result, "cache_hit": False, "publication_changed": False}
