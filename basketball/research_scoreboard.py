"""Bounded, keyless ESPN NBA scoreboard validation for private score research.

This is an unofficial ESPN site-facing endpoint, NOT an independent sports
data provider, SLA, commercial licence or real-time availability guarantee.
Never use it for public predictions, bookmaker markets, or unverified scores.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from basketball.research_data import _verify_game

SCOREBOARD_SOURCE = "espn:nba:scoreboard:v1"
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
CDN_URL = "https://cdn.espn.com/core/nba/scoreboard"
MAX_RESPONSE_BYTES = 4_000_000
MAX_DATES = 12
MAX_GAME_AGE_DAYS = 14


def _utc(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def selected_dates(games: list[dict], as_of: datetime,
                   pending_dates: list[str] | None = None) -> list[str]:
    """Select bounded source-local match dates with overdue unverified games.

    The schedule's game date is provider-local (usually US Eastern), unlike
    start_utc. Never derive the requested scoreboard date from UTC tipoff.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Scoreboard clock must be timezone-aware")
    now = as_of.astimezone(timezone.utc)
    earliest = now - timedelta(days=MAX_GAME_AGE_DAYS)
    recent = {}
    for game in games:
        if game["status"] == "final" or game.get("postseason"):
            continue
        start = _utc(game.get("start_utc"))
        if start is None or not earliest <= start <= now:
            continue
        recent[game["date"]] = max(recent.get(game["date"], 0),
                                    start.timestamp())
    # Score pending forecasts that remain unresolved beyond the default
    # recent window only when their date stays within the 14-day safety cap.
    for value in pending_dates or []:
        try:
            game_day = date.fromisoformat(value)
        except ValueError:
            continue
        if earliest.date() <= game_day <= now.date():
            recent.setdefault(value, 0)
    # Priority: newest dates first; at most 12 bounded no-key requests.
    return sorted(recent, reverse=True)[:MAX_DATES]


def _score(raw: object) -> int:
    text = str(raw).strip()
    if not text.isdecimal():
        raise ValueError("NBA final score must be a nonnegative integer")
    return int(text)


def parse_final_event(event: dict, *, retrieved_at: str) -> dict | None:
    """Reject nonfinal, postseason, malformed and ambiguous scoreboards."""
    if not isinstance(event, dict):
        raise ValueError("ESPN event must be an object")
    identity = str(event.get("id") or "")
    if not identity.isdecimal() or int(identity) <= 0:
        raise ValueError("ESPN event has no trusted numeric identifier")
    season = event.get("season") or {}
    if season.get("type") is not None and str(season["type"]) != "2":
        return None
    status = (event.get("status") or {}).get("type") or {}
    if (status.get("completed") is not True or
            status.get("state") != "post" or
            status.get("name") != "STATUS_FINAL"):
        return None
    competitions = event.get("competitions") or []
    if len(competitions) != 1:
        raise ValueError("Final NBA event requires a unique competition")
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    if len(competitors) != 2:
        raise ValueError("Final NBA game requires exactly two competitors")
    by_side = {}
    for competitor in competitors:
        venue = competitor.get("homeAway")
        team = competitor.get("team") or {}
        team_id = str(team.get("id") or "")
        if (venue not in ("home", "away") or venue in by_side or
                not team_id.isdecimal() or int(team_id) <= 0):
            raise ValueError("Ambiguous home/away ESPN final identity")
        by_side[venue] = (str(int(team_id)), _score(competitor.get("score")))
    if set(by_side) != {"home", "away"}:
        raise ValueError("Missing home or away final identity")
    if by_side["home"][1] == by_side["away"][1]:
        raise ValueError("A finished NBA basketball game cannot be tied")
    tipoff = _utc(event.get("date"))
    if tipoff is None:
        raise ValueError("Final ESPN game has no verified UTC kickoff")
    return {
        "game_id": str(int(identity)),
        "home_id": by_side["home"][0],
        "away_id": by_side["away"][0],
        "home_score": by_side["home"][1],
        "away_score": by_side["away"][1],
        "start_utc": tipoff.isoformat(),
        "source": SCOREBOARD_SOURCE,
        "retrieved_at": retrieved_at,
    }


def parse_scoreboard(payload: dict, *, retrieved_at: str) -> dict[str, dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("ESPN scoreboard has no events collection")
    if len(payload["events"]) > 100:
        raise ValueError("NBA scoreboard returned too many events")
    result = {}
    for event in payload["events"]:
        final = parse_final_event(event, retrieved_at=retrieved_at)
        if final is not None:
            ident = final["game_id"]
            if ident in result and result[ident] != final:
                raise ValueError("Conflicting ESPN final events for same game")
            result[ident] = final
    return result


def _fetch_json(url: str, *, expected_host: str, timeout: int) -> dict:
    """Only fixed, HTTPS NBA score hosts; bounded and URL-safe diagnostics."""
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BetSightlyPrivateNBAResearch/1.0)",
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            arrived = urlsplit(response.geturl())
            if arrived.scheme != "https" or arrived.hostname != expected_host:
                raise ValueError("UNEXPECTED_REDIRECT_HOST")
            if int(response.headers.get("Content-Length") or 0) > MAX_RESPONSE_BYTES:
                raise ValueError("RESPONSE_TOO_LARGE")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("RESPONSE_TOO_LARGE")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("NON_OBJECT_JSON")
        return payload
    except HTTPError as exc:
        raise RuntimeError(f"HTTP_{exc.code}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            error = "TIMEOUT"
        elif isinstance(reason, OSError) and getattr(reason, "errno", None) in (
                11001, -2, -3):
            error = "DNS_ERROR"
        else:
            error = "NETWORK_ERROR"
        raise RuntimeError(error) from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError("TRANSPORT_ERROR") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("INVALID_JSON") from exc
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _cdn_scoreboard(payload: dict) -> dict:
    # ESPN's CDN exposes the site-scoreboard shape under sbData; accept
    # either a dict or a JSON-encoded dict, never infer score fields.
    body = payload.get("sbData")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("CDN_INVALID_SBDATA") from exc
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        raise RuntimeError("CDN_MISSING_EVENTS")
    return body


def download_scoreboard(day: str, *, timeout: int = 15) -> dict:
    """Try site API then CDN. Both are ESPN; neither is a second provider."""
    date.fromisoformat(day)
    if not 1 <= timeout <= 60:
        raise ValueError("Invalid NBA scoreboard timeout")
    day_arg = day.replace("-", "")
    primary = BASE_URL + "?dates=" + day_arg + "&seasontype=2&limit=100"
    cdn = CDN_URL + "?xhr=1&date=" + day_arg + "&seasontype=2"
    errors = []
    for transport, url, host in (
            ("site", primary, "site.api.espn.com"),
            ("cdn", cdn, "cdn.espn.com")):
        try:
            payload = _fetch_json(url, expected_host=host, timeout=timeout)
            if transport == "cdn":
                payload = _cdn_scoreboard(payload)
            if not isinstance(payload.get("events"), list):
                raise RuntimeError("MISSING_EVENTS")
            return payload
        except RuntimeError as exc:
            # Status and failure category are safe to log. Do NOT log raw
            # responses, query strings or any provider-controlled HTML.
            errors.append(f"{transport}:{str(exc)[:50]}")
    raise RuntimeError("SCOREBOARD_UNAVAILABLE " + "; ".join(errors))


def verify_finals(games: list[dict], finals: dict[str, dict]) -> tuple[list[dict], dict]:
    """Apply scores ONLY to exact source fixture id, teams and kickoff.

    Reject score corrections/conflicts rather than mutating settled history.
    Preserve provider-local 'date' so the existing ledger matches fixture ID
    and date; do not copy the scoreboard's UTC date over it.
    """
    by_id = {}
    changed = 0
    ignored = 0
    for game in games:
        _verify_game(game)
        ident = str(game["game_id"])
        result = finals.get(ident)
        if result is None:
            by_id[ident] = game
            continue
        if (str(game["home_id"]) != result["home_id"] or
                str(game["away_id"]) != result["away_id"]):
            raise ValueError("NBA final team identity mismatch for " + ident)
        game_start = _utc(game.get("start_utc"))
        final_start = _utc(result["start_utc"])
        if (game_start is None or final_start is None or
                abs((game_start - final_start).total_seconds()) > 3600 * 12):
            raise ValueError("NBA final kickoff identity mismatch for " + ident)
        if game["status"] == "final":
            if (game["home_score"], game["away_score"]) != (
                    result["home_score"], result["away_score"]):
                raise ValueError("Conflicting verified NBA final for " + ident)
            by_id[ident] = game
            ignored += 1
            continue
        by_id[ident] = {
            **game, "status": "final",
            "home_score": result["home_score"],
            "away_score": result["away_score"],
            "source": SCOREBOARD_SOURCE,
            "retrieved_at": result["retrieved_at"],
        }
        _verify_game(by_id[ident])
        changed += 1
    return list(by_id.values()), {
        "verified_new_finals": changed,
        "already_final": ignored,
        "unmatched_events": len(set(finals).difference(by_id)),
    }


def preserve_older_verified_finals(fresh: list[dict],
                                    previous: list[dict]) -> tuple[list[dict], int]:
    """Do not regress a prior verified FINAL when a release asset lags.

    A conflicting final or changed identity fails closed before any disk write.
    """
    old = {str(g["game_id"]): g for g in previous if g["status"] == "final"}
    restored = 0
    result = []
    for game in fresh:
        before = old.get(str(game["game_id"]))
        if before is None:
            result.append(game)
            continue
        if any(str(game[field]) != str(before[field]) for field in (
                "game_id", "date", "season", "home_id", "away_id")):
            raise ValueError("NBA historical final identity conflict")
        if game["status"] == "final":
            if (game["home_score"], game["away_score"]) != (
                    before["home_score"], before["away_score"]):
                raise ValueError("NBA historical final score conflict")
            result.append(game)
        else:
            result.append(before)
            restored += 1
    return result, restored


def refresh_recent_finals(games: list[dict], *,
                          as_of: datetime,
                          pending_dates: list[str] | None = None,
                          loader=None) -> tuple[list[dict], dict]:
    """Bounded best-effort scoreboard refresh; never invent a final score.

    Provider errors are explicit but do not erase an otherwise verified
    historical snapshot. Invalid identities/conflicting scores DO fail closed.
    """
    loader = loader or download_scoreboard
    dates = selected_dates(games, as_of, pending_dates=pending_dates)
    recovered = {}
    errors = []
    checked = 0
    for day in dates:
        try:
            raw = loader(day)
            finals = parse_scoreboard(
                raw, retrieved_at=as_of.astimezone(timezone.utc).isoformat())
        except (RuntimeError, HTTPError, URLError, TimeoutError, OSError,
                ValueError, KeyError, TypeError) as exc:
            errors.append({"date": day, "error": type(exc).__name__,
                           "detail": str(exc)[:160] if isinstance(exc, RuntimeError)
                           else type(exc).__name__})
            continue
        checked += 1
        for ident, final in finals.items():
            if ident in recovered and recovered[ident] != final:
                raise ValueError("Conflicting ESPN final across days")
            recovered[ident] = final
    merged, stats = verify_finals(games, recovered)
    summary = {
        "status": "partial" if errors else "ok",
        "source": SCOREBOARD_SOURCE,
        "dates_requested": len(dates),
        "dates_checked": checked,
        "failed_dates": errors,
        **stats,
        "verified_provider": "ESPN scoreboard (unofficial, keyless)",
        "commercial_use_cleared": False,
    }
    return merged, summary
