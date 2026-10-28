"""Conservative, keyless NBA-only settlement for private basketball bookings.

ESPN scoreboard is evidence, not a fixture oracle: no score is applied unless
both team identities, tipoff date/time, competition, completed flag and numeric
final totals uniquely match. Non-NBA tickets remain pending until an audited
score provider is added for their league.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
MATCH_WINDOW_SECONDS = 3 * 3600


def _now():
    return datetime.now(timezone.utc)


def _iso_date(raw):
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _identity(value):
    cleaned = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    # ESPN sometimes calls the Clippers "Los Angeles Clippers" vs Sporty "LA Clippers".
    return "losangelesclippers" if cleaned in {"laclippers", "losangelesclippers"} else cleaned


def _event_record(event):
    """Accept only full-game completed, exact home/away NBA results."""
    if (event.get("status") or {}).get("type", {}).get("completed") is not True:
        return None
    matches = event.get("competitions") or []
    if len(matches) != 1:
        return None
    teams = matches[0].get("competitors") or []
    if len(teams) != 2:
        return None
    home = next((team for team in teams if team.get("homeAway") == "home"), None)
    away = next((team for team in teams if team.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    def extract(team):
        name = ((team.get("team") or {}).get("displayName") or "")
        number = team.get("score")
        if not name or number is None:
            return None
        try:
            integer = int(number)
            if integer < 0 or str(number).strip() != str(integer):
                return None
            return (name, integer)
        except (TypeError, ValueError):
            return None
    h, a = extract(home), extract(away)
    tipoff = _iso_date(event.get("date"))
    if not h or not a or not tipoff or not event.get("id"):
        return None
    return {"source": "ESPN_NBA_FINAL", "source_event_id": str(event["id"]),
            "home": h[0], "away": a[0], "home_score": h[1],
            "away_score": a[1], "tipoff": tipoff}


def _fetch_day(day, *, get=None):
    import requests
    fetch = get or requests.get
    res = fetch(SCOREBOARD, params={"dates": day, "limit": 100}, timeout=12)
    res.raise_for_status()
    data = res.json()
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("Invalid ESPN NBA scoreboard payload.")
    return [item for event in data["events"]
            if (item := _event_record(event)) is not None]


def _match(leg, finals):
    if str(leg.get("competition") or "").strip().upper() != "NBA":
        return None
    try:
        kickoff = datetime.fromtimestamp(int(leg["kickoff_ms"]) / 1000, tz=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return None
    matches = [event for event in finals
               if _identity(event["home"]) == _identity(leg.get("home_team"))
               and _identity(event["away"]) == _identity(leg.get("away_team"))
               and abs((event["tipoff"] - kickoff).total_seconds()) <= MATCH_WINDOW_SECONDS]
    unique = {event["source_event_id"]: event for event in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None


def settle_leg(leg, event):
    """Do not change the market, specifier or bookmaker outcome ID."""
    candidate = dict(leg)
    try:
        h, a = event["home_score"], event["away_score"]
        market, outcome = str(leg["market_id"]), str(leg["outcome_id"])
        if market == "219" and leg.get("specifier", "") == "":
            if h == a:
                return candidate  # A basketball winner needs a decisive final.
            win = (h > a and outcome == "4") or (a > h and outcome == "5")
            if outcome not in {"4", "5"}:
                return candidate
            result = "won" if win else "lost"
        elif market == "225" and outcome in {"12", "13"}:
            match = re.fullmatch(r"total=(\d+(?:\.\d+)?)", str(leg.get("specifier") or ""))
            if not match:
                return candidate
            line = float(match.group(1))
            if h + a == line:
                result = "void"
            else:
                won = (h + a > line) if outcome == "12" else (h + a < line)
                result = "won" if won else "lost"
        else:
            from growth.basketball_market_grades import grade_team_total
            result = grade_team_total(leg, home_points=h, away_points=a)
            if result is None:
                return candidate
    except (KeyError, TypeError, ValueError):
        return candidate
    candidate["result"] = result
    candidate["score"] = {"home": h, "away": a}
    candidate["score_source"] = event["source"]
    candidate["score_event_id"] = event["source_event_id"]
    candidate["settled_at"] = _now().isoformat()
    return candidate


def _ticket_status(legs):
    statuses = [leg.get("result") or "pending" for leg in legs]
    if "lost" in statuses:
        return "lost"
    if not statuses or "pending" in statuses:
        return "pending"
    if all(s == "void" for s in statuses):
        return "void"
    if all(s in {"won", "void"} for s in statuses):
        return "won"
    return "pending"


def settle_due(*, get=None, force=False):
    """Reconcile verified NBA, EuroLeague and EuroCup finals, never guesses."""
    from growth import basketball_history as history
    from growth import basketball_europe_finals as european

    start = _now()
    records = history.list_recent(limit=100)["tickets"]
    due = []
    for ticket in records:
        if ticket["status"] not in {"active", "won", "lost", "void"}:
            continue
        check = _iso_date(ticket.get("last_checked_at"))
        if not force and check and (start - check).total_seconds() < 600:
            continue
        for leg in ticket["legs"]:
            if leg.get("result") in {"won", "lost", "void"}:
                continue
            competition = str(leg.get("competition") or "").strip().upper()
            if competition not in {"NBA", "EUROLEAGUE", "EUROCUP"}:
                continue
            try:
                scheduled = datetime.fromtimestamp(int(leg["kickoff_ms"]) / 1000, timezone.utc)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if scheduled + timedelta(minutes=90) <= start:
                due.append((ticket, leg, scheduled, competition))
    if not due:
        return {"status": "success", "nba_final_legs": 0,
                "verified_final_legs": 0, "tickets_updated": 0}

    # The NBA uses ESPN's day-indexed calendar; international results are
    # retrieved only for the exact competition/season of unresolved legs.
    nba_due = [(ticket, leg, time) for ticket, leg, time, comp in due if comp == "NBA"]
    days = sorted({(kickoff + timedelta(days=delta)).strftime("%Y%m%d")
                   for _, _, kickoff in nba_due for delta in (-1, 0, 1)})[:12]
    nba_results = {}
    european_results = []
    failures = []
    for day in days:
        try:
            for event in _fetch_day(day, get=get):
                nba_results[event["source_event_id"]] = event
        except Exception as exc:
            failures.append(f"NBA {day}: {type(exc).__name__}")
    pairs = sorted({(competition, (scheduled.year if scheduled.month >= 7
                                   else scheduled.year - 1))
                    for _, _, scheduled, competition in due
                    if competition in {"EUROLEAGUE", "EUROCUP"}})
    for competition, season_year in pairs:
        try:
            european_results.extend(european.fetch_finals(competition, season_year, get=get))
        except Exception as exc:
            failures.append(f"{competition} {season_year}: {type(exc).__name__}")

    # Keep all evidence isolated to the provider/competition. Partial provider
    # failures may never be construed as absent finals or a lost ticket.
    nba_finals = list(nba_results.values())
    touched, legs_marked, nba_marked = 0, 0, 0
    tickets = {ticket["fingerprint"]: ticket for ticket, _, _, _ in due}
    for ticket in tickets.values():
        changed = False
        updated = []
        for leg in ticket["legs"]:
            if leg.get("result") in {"won", "lost", "void"}:
                updated.append(leg)
                continue
            competition = str(leg.get("competition") or "").strip().upper()
            event = (_match(leg, nba_finals) if competition == "NBA"
                     else european.match_final(leg, european_results)
                     if competition in {"EUROLEAGUE", "EUROCUP"} else None)
            newer = settle_leg(leg, event) if event else leg
            marked = (newer.get("result") in {"won", "lost", "void"}
                      and newer.get("result") != leg.get("result"))
            changed |= marked
            legs_marked += int(marked)
            nba_marked += int(marked and competition == "NBA")
            updated.append(newer)
        # Do not update a ticket's audit timestamp if none of its source
        # providers was successfully observed and it has not changed.
        if changed or not failures:
            history.update_results(ticket["fingerprint"], updated, _now().isoformat(),
                                   _ticket_status(updated))
        touched += int(changed)
    return {"status": "SCORE_PROVIDER_PARTIAL" if failures else "success",
            "nba_final_legs": nba_marked, "verified_final_legs": legs_marked,
            "tickets_updated": touched,
            "providers": ["ESPN_NBA_FINAL", "EUROLEAGUE_OFFICIAL_FINAL"],
            "failures": failures}
