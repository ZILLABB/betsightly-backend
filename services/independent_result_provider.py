"""Independent score-provider bridge for BetSightly's *separate* manual ledger.

Provider A: API-Sports / API-Football v3. Provider B can emit exactly the
same normalized observation schema. Strict bookmaker-fixture identity is
resolved once; provisional scores can never cause settlement. This module
has no credentials, database mutations, bookmaker calls, or Telegram access.

A nonempty, provider-verified identity is mandatory for scored evidence.
The API account/license enablement remains an explicit operational gate.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

_TERMINAL = {"FT", "AET", "PEN"}
_REJECTED = {"PST", "CANC", "ABD", "AWD", "WO", "SUSP", "INT", "TBD"}
_MAX_ID = 18


def _utc(value: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _score(value: object) -> int | None:
    # Do not let True, 1.4, blank or other implicit values become goals.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 60 else None


def parse_api_football_fixture(entry: dict) -> dict | None:
    """Interpret API-Sports fixture ID, teams, UTC kickoff and 90' scores.

    Accept extra-time and penalties only from explicit score.fulltime fields,
    never final 'goals' fields that may include extra-time goals.
    """
    if not isinstance(entry, dict):
        return None
    fixture = entry.get("fixture") or {}
    teams = entry.get("teams") or {}
    league = entry.get("league") or {}
    if not all(isinstance(x, dict) for x in (fixture, teams, league)):
        return None
    fid = fixture.get("id")
    league_id = league.get("id")
    home, away = teams.get("home") or {}, teams.get("away") or {}
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    when = _utc(fixture.get("date"))
    if (not isinstance(fid, int) or isinstance(fid, bool) or fid <= 0
            or len(str(fid)) > _MAX_ID or when is None):
        return None
    hname, aname = str(home.get("name") or "").strip(), str(away.get("name") or "").strip()
    if not hname or not aname or hname.casefold() == aname.casefold():
        return None
    status = (fixture.get("status") or {})
    if not isinstance(status, dict):
        return None
    state = str(status.get("short") or "").upper()
    final = None
    if state in _TERMINAL:
        scores = entry.get("score") or {}
        ft = scores.get("fulltime") if isinstance(scores, dict) else None
        if isinstance(ft, dict):
            hs, vs = _score(ft.get("home")), _score(ft.get("away"))
            if hs is not None and vs is not None:
                final = {"home": hs, "away": vs}
    return {
        "source": "api-football",
        "event_id": str(fid),
        "league_id": str(league_id) if isinstance(league_id, int) and league_id > 0 else None,
        "home_team": hname,
        "away_team": aname,
        "home_team_id": str(home.get("id") or ""),
        "away_team_id": str(away.get("id") or ""),
        "kickoff_utc": when.isoformat(),
        "status": state,
        "completed": final is not None,
        "score_90": final,
        "requires_adjudication": state in _REJECTED,
    }


def normalize_observations(response: dict) -> list[dict]:
    """Reject API errors and malformed replies instead of treating them as empty games."""
    if not isinstance(response, dict) or response.get("errors"):
        raise ValueError("Provider response is unavailable or indicates an account/quota error")
    events = response.get("response")
    if not isinstance(events, list):
        raise ValueError("Provider returned no valid fixture response array")
    return [parsed for event in events
            if (parsed := parse_api_football_fixture(event)) is not None]


def _name(value: object) -> str:
    # Reuse the project's explicitly corroborated complete-club aliases, not
    # fuzzy/substring guesses; never remove youth/women/reserve distinctions.
    from leagues.results_checker import _normalize_name
    return _normalize_name(str(value or ""))


def _pick_time(pick: dict) -> datetime | None:
    return _utc(pick.get("commence_time") or pick.get("kickoff")
                or pick.get("kickoff_utc") or pick.get("date"))


def unique_fixture_links(picks: list[dict], rows: list[dict]) -> dict[str, dict]:
    """Unique strict teams+kickoff+optional league crosswalk and event ID.

    These links are candidates for immutable manual ledger storage, NOT
    proof that an in-play score is full-time. Any potential one-to-many
    mapping remains uncovered until deliberately adjudicated.
    """
    output: dict[str, dict] = {}
    seen: dict[str, set[str]] = {}
    for pick in picks:
        mid = str(pick.get("match_id") or "")
        when = _pick_time(pick)
        home, away = _name(pick.get("home_team")), _name(pick.get("away_team"))
        if not mid or not when or not home or not away or home == away:
            continue
        required_league = str(pick.get("api_football_league_id") or "").strip()
        matches = [
            row for row in rows
            if row.get("source") == "api-football"
            and row.get("event_id", "").isdigit()
            and (not required_league or required_league == row.get("league_id"))
            and _name(row.get("home_team")) == home
            and _name(row.get("away_team")) == away
            and (kickoff := _utc(row.get("kickoff_utc"))) is not None
            and abs((kickoff - when).total_seconds()) <= 20*60
        ]
        if len(matches) != 1:
            continue
        winner = matches[0]
        proposal = {
            "provider": "api-football",
            "event_id": winner["event_id"],
            "source_league_id": winner.get("league_id"),
            "kickoff_utc": when.isoformat(),
            "source_kickoff_utc": winner["kickoff_utc"],
            "bookmaker_event_id": str(pick.get("sportybet_event_id") or ""),
            "score_verified": False,
        }
        if mid in output and output[mid] != proposal:
            seen.setdefault(mid, set()).update(
                {output[mid]["event_id"], proposal["event_id"]}
            )
        elif mid not in seen:
            output[mid] = proposal

    for mid in seen:
        output.pop(mid, None)
    # One source event cannot represent two different bookmaker matches.
    by_source: dict[str, set[str]] = {}
    for mid, link in output.items():
        by_source.setdefault(link["event_id"], set()).add(mid)
    return {mid: link for mid, link in output.items()
            if len(by_source[link["event_id"]]) == 1}


def verified_final_for_link(pick: dict, link: dict,
                            rows: list[dict]) -> dict | None:
    """Return normal legacy settlement evidence ONLY for exact linked FT 90'."""
    if not isinstance(link, dict) or link.get("provider") != "api-football":
        return None
    when = _pick_time(pick)
    event = str(link.get("event_id") or "")
    if not when or not event.isdigit():
        return None
    matches = [
        row for row in rows
        if row.get("source") == "api-football"
        and row.get("event_id") == event
    ]
    if len(matches) != 1:
        return None
    result = matches[0]
    when_provider = _utc(result.get("kickoff_utc"))
    if (not when_provider
            or abs((when_provider-when).total_seconds()) > 20*60
            or result.get("league_id") != link.get("source_league_id")
            or _name(result.get("home_team")) != _name(pick.get("home_team"))
            or _name(result.get("away_team")) != _name(pick.get("away_team"))
            or result.get("status") not in _TERMINAL
            or not result.get("completed")):
        return None
    score = result.get("score_90")
    if not isinstance(score, dict):
        return None
    hs, vs = _score(score.get("home")), _score(score.get("away"))
    if hs is None or vs is None:
        return None
    return {
        "home": result["home_team"], "away": result["away_team"],
        "date": when.date().isoformat(),
        "completed": True, "provider": "api-football",
        "provider_event_id": event, "league_id": result.get("league_id"),
        "home_score": hs, "away_score": vs,
        "score_90": {"home": hs, "away": vs},
        "match_status": result["status"],
    }


def readiness(picks: list[dict], observations: list[dict]) -> dict:
    """Read-only dry-run evidence to choose supplier/league subscription."""
    linked = unique_fixture_links(picks, observations)
    pending = [p for p in picks if p.get("status") not in {"won", "lost", "void"}]
    fully_supported = sum(
        verified_final_for_link(p, linked.get(str(p.get("match_id")), {}), observations)
        is not None for p in pending
    )
    missing = Counter(str(p.get("league") or "Unspecified")
                      for p in pending if str(p.get("match_id")) not in linked)
    return {
        "mode": "shadow_read_only", "provider": "api-football",
        "pending_legs": len(pending),
        "uniquely_matched": len(linked),
        "strict_verified_90min_finals": fully_supported,
        "unlinked_by_bookmaker_league": dict(missing.most_common()),
        "booking_codes_created": 0, "published_outcomes_changed": 0,
        "requires_confirmed_commercial_rights_for_activation": True,
    }


def chunk_ids(ids: list[str], size: int = 20) -> list[str]:
    """API-Football supports at most 20 numeric fixture IDs per request."""
    if not 1 <= size <= 20:
        raise ValueError("Provider batch size must be 1..20")
    valid = sorted({str(i) for i in ids
                    if str(i).isdigit() and 0 < int(i) < 10**_MAX_ID},
                   key=int)
    return ["-".join(valid[i:i+size]) for i in range(0, len(valid), size)]
