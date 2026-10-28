"""Quarantined cross-provider football fixture identity for Jev evidence.

The caller must supply an explicit original ESPN fixture, an OpenLigaDB
normalized snapshot and a pre-kickoff observation timestamp. NEVER infer
identity from a score, a team's substring, a league name or a single match.
Matches with ambiguous identity or stale evidence return no observations.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import unicodedata
from typing import Any

from leagues.jev_evidence_contract import _utc, evidence_envelope

LEAGUE_MAP = {"ger.1": "bl1", "ger.2": "bl2"}
MAX_KICKOFF_DRIFT = timedelta(minutes=10)
MAX_SOURCE_AGE = timedelta(hours=12)
MAX_EVIDENCE_PER_GAME = 8


def _team(value: str | None) -> str:
    """Conservative normalization: accents/punctuation, not fuzzy identity."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(x for x in text if not unicodedata.combining(x))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _selection(pick: dict) -> dict[str, Any]:
    """Read either raw engine pick or frontend-compatible game shape."""
    fx = pick.get("_fixture") or {}
    return {
        "match_id": str(pick.get("match_id") or fx.get("match_id") or ""),
        "market": str(pick.get("market") or ""),
        "kickoff": (pick.get("kickoff") or pick.get("date")
                    or fx.get("commence_time")),
        "league_slug": str(pick.get("league_slug") or fx.get("league_slug") or ""),
        "home_team": str(pick.get("home_team") or (fx.get("home") or {}).get("name") or ""),
        "away_team": str(pick.get("away_team") or (fx.get("away") or {}).get("name") or ""),
        "odds": pick.get("odds"),
        "selection_probability": pick.get("selection_probability",
                                          pick.get("confidence")),
        "market_trust_state": pick.get("market_trust_state"),
    }


def match_source_fixture(
    pick: dict, snapshot: dict, *, as_of: datetime,
) -> dict[str, Any]:
    """Match both sides + competition + kickoff, rejecting all ambiguity."""
    s = _selection(pick)
    at = _utc(as_of)
    kickoff = _utc(s["kickoff"])
    if at is None:
        raise ValueError("as_of requires a timezone")
    if not s["match_id"] or not s["market"] or not kickoff or kickoff <= at:
        return {"status": "quarantined", "reason": "invalid_or_started_prediction"}
    league = LEAGUE_MAP.get(s["league_slug"])
    if league is None:
        return {"status": "unsupported_league", "reason": "no_approved_league_mapping"}
    if (snapshot.get("status") != "ok" or snapshot.get("source_id") != "openligadb"
            or snapshot.get("license") != "ODbL"):
        return {"status": "quarantined", "reason": "untrusted_or_unavailable_snapshot"}
    captured = _utc(snapshot.get("captured_at"))
    if (not captured or captured > at or at - captured > MAX_SOURCE_AGE
            or captured >= kickoff):
        return {"status": "quarantined", "reason": "future_stale_or_post_kickoff_snapshot"}
    home, away = _team(s["home_team"]), _team(s["away_team"])
    if not home or not away or home == away:
        return {"status": "quarantined", "reason": "invalid_team_identity"}
    matches = []
    for fixture in snapshot.get("fixtures") or []:
        if not isinstance(fixture, dict) or fixture.get("source_id") != "openligadb":
            continue
        event_kickoff = _utc(fixture.get("kickoff_utc"))
        if (fixture.get("league_shortcut") != league or not event_kickoff
                or abs(event_kickoff - kickoff) > MAX_KICKOFF_DRIFT):
            continue
        if (_team(fixture.get("home_team")) == home
                and _team(fixture.get("away_team")) == away):
            matches.append(fixture)
    if len(matches) != 1:
        return {"status": "quarantined",
                "reason": "ambiguous_fixture" if matches else "fixture_not_matched",
                "candidate_count": len(matches)}
    match = matches[0]
    identity = str(match.get("provider_match_id") or "")
    # Conflicting duplicate provider identity elsewhere in this snapshot is a
    # source corruption, not a second possible spelling of the same game.
    duplicate = sum(str(f.get("provider_match_id")) == identity
                    for f in snapshot.get("fixtures") or [] if isinstance(f, dict))
    if not identity or duplicate != 1:
        return {"status": "quarantined", "reason": "provider_fixture_id_reused"}
    return {"status": "matched", "fixture": match, "selection": s,
            "external_match_id": identity, "mapping_verified": True,
            "attribution": snapshot.get("attribution")}


def matched_evidence_envelope(pick: dict, snapshot: dict, *,
                              as_of: datetime) -> dict[str, Any]:
    """Only the unique matched *pregame* observation enters Jev state."""
    result = match_source_fixture(pick, snapshot, as_of=as_of)
    if result.get("status") != "matched":
        return {"status": "quarantined", "reason": result.get("reason"),
                "publication_authority": False, "shadow_only": True}
    match = result["fixture"]
    source = f"openligadb:{match['league_shortcut']}:{match['provider_match_id']}"
    obs = [
        row for row in (snapshot.get("evidence") or [])
        if isinstance(row, dict)
        and row.get("source_id") == source
        and row.get("type") == "competition_schedule"
        and row.get("source_url") == match.get("source_url")
    ][:MAX_EVIDENCE_PER_GAME]
    if not obs:
        return {"status": "quarantined", "reason": "no_matching_pregame_evidence",
                "publication_authority": False, "shadow_only": True}
    envelope = evidence_envelope(result["selection"], obs, sport="football",
                                 as_of=as_of)
    if envelope.get("evidence_count") != len(obs):
        return {"status": "quarantined", "reason": "evidence_failed_timestamp_gate",
                "publication_authority": False, "shadow_only": True}
    envelope["source_fixture_identity"] = {
        "original_fixture_id": result["selection"]["match_id"],
        "external_fixture_id": result["external_match_id"],
        "provider": "openligadb",
        "attribution": result["attribution"],
        "match_policy": "strict-home-away-league-10m-v1",
    }
    return envelope
