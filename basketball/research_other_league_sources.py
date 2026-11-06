"""Read-only candidate scoreboard discovery for *other* basketball leagues.

Not an approved NBA forecast input, no mutation of the NBA archive and
no automatic non-NBA ticket settlement. Providers require separate acceptance
for names, missing dates, competition rules and player statistics.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

CANDIDATES = {
    "wnba": {
        "espn_slug": "wnba", "research_state": "source_candidate",
        "period_length_minutes": 10,
    },
    "ncaa_men": {
        "espn_slug": "mens-college-basketball", "research_state": "source_candidate",
        "period_length_minutes": 20,
    },
    "ncaa_women": {
        "espn_slug": "womens-college-basketball", "research_state": "source_candidate",
        "period_length_minutes": 10,
    },
    "nbl_au": {
        "espn_slug": "nbl", "research_state": "source_candidate",
        "period_length_minutes": 10,
    },
}
HOST = "https://site.api.espn.com/apis/site/v2/sports/basketball"
MAX_EVENTS = 100


def source_url(league: str, day: str) -> str:
    if league not in CANDIDATES or not re.fullmatch(r"20\d{6}", day):
        raise ValueError("LEAGUE_OR_DATE_NOT_SUPPORTED")
    return HOST + "/" + CANDIDATES[league]["espn_slug"] + "/scoreboard?dates=" + day + "&limit=100"


def parse_candidate_final(league: str, event: dict):
    """Verify bare score identities; make *no* model or bookmaker claims."""
    if league not in CANDIDATES or not isinstance(event, dict):
        return None
    if (event.get("status") or {}).get("type", {}).get("completed") is not True:
        return None
    competitions = event.get("competitions") or []
    if len(competitions) != 1:
        return None
    comps = competitions[0].get("competitors") or []
    if len(comps) != 2:
        return None
    away = next((c for c in comps if c.get("homeAway") == "away"), None)
    home = next((c for c in comps if c.get("homeAway") == "home"), None)
    if not away or not home or away is home:
        return None
    def unpack(row):
        team = row.get("team") or {}
        identifier = str(team.get("id") or "")
        name = str(team.get("displayName") or "")
        raw = str(row.get("score") or "")
        if not identifier or not name or not raw.isdecimal():
            return None
        score = int(raw)
        if not 0 <= score < 400:
            return None
        return {"team_id": identifier, "team": name, "score": score}
    h, a = unpack(home), unpack(away)
    if not h or not a or h["team_id"] == a["team_id"]:
        return None
    raw_dt = str(event.get("date") or "")
    try:
        tipoff = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
    except ValueError:
        return None
    if tipoff.tzinfo is None:
        return None
    event_id = str(event.get("id") or "")
    if not event_id.isdecimal():
        return None
    return {
        "competition": league, "provider": "espn_site_scoreboard_candidate",
        "provider_event_id": event_id,
        "tipoff_utc": tipoff.astimezone(timezone.utc).isoformat(),
        "home": h, "away": a,
        "total": h["score"] + a["score"],
        "research_only": True, "not_bookable": True,
        "validation_status": "source_candidate_not_model_approved",
    }


def parse_candidate_fixture(league: str, event: dict):
    """Identify a scheduled or final event without inventing betting evidence."""
    if league not in CANDIDATES or not isinstance(event, dict):
        return None
    ident = str(event.get("id") or "")
    if not ident.isdecimal() or len(ident) > 24:
        return None
    items = event.get("competitions")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    pair = items[0].get("competitors")
    if not isinstance(pair, list) or len(pair) != 2:
        return None
    sides = {}
    for competitor in pair:
        if not isinstance(competitor, dict) or competitor.get("homeAway") not in ("home", "away"):
            return None
        side = competitor["homeAway"]
        team = competitor.get("team")
        if side in sides or not isinstance(team, dict):
            return None
        team_id = str(team.get("id") or "")
        if not team_id.isdecimal() or not str(team.get("displayName") or "").strip():
            return None
        sides[side] = team_id
    if set(sides) != {"home", "away"} or sides["home"] == sides["away"]:
        return None
    try:
        tip = datetime.fromisoformat(str(event.get("date") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if tip.tzinfo is None or tip.utcoffset() is None:
        return None
    state = (event.get("status") or {}).get("type") or {}
    if not isinstance(state, dict):
        return None
    completed = state.get("completed") is True
    return {
        "provider_event_id": ident,
        "tipoff_utc": tip.astimezone(timezone.utc).isoformat(),
        "home_id": sides["home"], "away_id": sides["away"],
        "completed": completed,
        "research_only": True, "not_bookable": True,
    }


def audit_candidate_payload(league: str, body: dict) -> dict:
    if league not in CANDIDATES or not isinstance(body, dict):
        raise ValueError("INVALID_CANDIDATE_PAYLOAD")
    events = body.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("CANDIDATE_SOURCE_INCOMPLETE")
    finals = []
    for event in events:
        item = parse_candidate_final(league, event)
        if item is not None:
            finals.append(item)
    fixtures = [parsed for event in events
                if (parsed := parse_candidate_fixture(league, event)) is not None]
    ids = [e["provider_event_id"] for e in fixtures]
    if len(set(ids)) != len(ids):
        raise ValueError("DUPLICATED_PROVIDER_GAME")
    final_ids = [e["provider_event_id"] for e in finals]
    if len(set(final_ids)) != len(final_ids):
        raise ValueError("DUPLICATED_PROVIDER_GAME")
    if any(fid not in set(ids) for fid in final_ids):
        raise ValueError("CANDIDATE_FINAL_WITHOUT_VERIFIED_FIXTURE")
    return {
        "league": league, "research_only": True, "not_bookable": True,
        "source": "espn_site_scoreboard_candidate",
        "events_observed": len(events), "exact_completed": len(finals),
        "identity_complete_fixtures": len(fixtures),
        "scheduled_identity_complete": sum(not f["completed"] for f in fixtures),
        "identity_incomplete_events": len(events) - len(fixtures),
        "candidate_fixtures": fixtures,
        "candidate_finals": finals,
        "approved_for_model_training": False,
        "approved_for_non_nba_booking_settlement": False,
        "reason": "Cross-source comparison, team identity mapping and longitudinal completeness not yet proven.",
    }


def probe_candidate_source(league: str, day: str, *, get=None) -> dict:
    """One bounded, non-mutating live source read for an approved league/date.

    No silent retries, no season-wide scraper, no NBA training archive writes.
    """
    import requests
    request = get or requests.get
    url = source_url(league, day)
    response = request(url, timeout=12, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError("CANDIDATE_PROVIDER_UNAVAILABLE")
    if len(response.content) > 2_000_000:
        raise ValueError("CANDIDATE_PROVIDER_TOO_LARGE")
    data = response.json()
    result = audit_candidate_payload(league, data)
    return {**result, "requested_date": day, "source_status": "one_day_probed"}


if __name__ == "__main__":
    # Explicit operator-only audit. Never launch an unbounded historical crawl.
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = probe_candidate_source(args.league, args.date)
    print(json.dumps({key: value for key, value in result.items()
                      if key != "candidate_finals"}, sort_keys=True))
