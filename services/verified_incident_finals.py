"""Auditable incident evidence for verified finals absent from settlement feeds.

Records here are strictly limited to a reviewed fixture/date/event ID. They
must be supported by a federation or club match report, not by a prediction or
a bookmaker's live odds. Keep the source URL in each persisted settlement.
Do not apply these records to an event merely because its teams look similar.

This recovery covers 14 October 2026; it is not a substitute for adding wider
first-party score-provider coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Exact SportyBet IDs are from the immutable 2026-10-14 Rollover Day 1 receipt.
# Sources independently confirm the 90-minute full-time scores:
# AFC for the two Asian matches, and Bohemians' own match report.
_VERIFIED_FINALS = (
    {
        "sportybet_event_id": "sr:match:73835212",
        "home": "Al-Taawoun FC", "away": "Al Rayyan SC",
        "date": "2026-10-14", "home_score": 2, "away_score": 1,
        "evidence_url": "https://www.the-afc.com/en/club/afc_champions_league_two.html/news/group-c-al-taawoun-fc-ksa-2-1-al-rayyan-sc-qat",
    },
    {
        "sportybet_event_id": "sr:match:75339776",
        "home": "Bohemians Prague 1905", "away": "FK Mlada Boleslav",
        "date": "2026-10-14", "home_score": 1, "away_score": 0,
        "evidence_url": "https://bohemians.cz/zapasy/MUZ/",
    },
    {
        "sportybet_event_id": "sr:match:73835214",
        "home": "AL Faisaly (Jor)", "away": "Al Nahda",
        "date": "2026-10-14", "home_score": 2, "away_score": 0,
        "evidence_url": "https://www.the-afc.com/en/club/afc_champions_league_two.html/news/group-c-al-faisaly-jor-x-x-al-nahda-oma-1",
    },
    # Official club match reports for UEFA Conference League round 1,
    # Thursday 15 October 2026. SportyBet IDs and kickoff dates are taken
    # from the *already published* Rollover Day 1 record.
    {
        "sportybet_event_id": "sr:match:74173148",
        "home": "Gent", "away": "AGF Aarhus",
        "date": "2026-10-15", "home_score": 1, "away_score": 0,
        "evidence_url": "https://www.kaagent.be/nl/nieuws/15-10-2026/te-lang-gewacht-om-onszelf-te-belonen",
    },
    {
        "sportybet_event_id": "sr:match:74173204",
        "home": "Freiburg", "away": "FK Jablonec",
        "date": "2026-10-15", "home_score": 3, "away_score": 2,
        "evidence_url": "https://www.scfreiburg.com/en/latest/first-team/match-reports/2026-27/sc-make-winning-start-to-league-phase/",
    },
    {
        "sportybet_event_id": "sr:match:74173182",
        "home": "Brighton", "away": "FK Kauno Zalgiris",
        "date": "2026-10-15", "home_score": 4, "away_score": 0,
        "evidence_url": "https://www.uefa.com/uefaconferenceleague/clubs/2605907/matches/",
    },
)


def incident_finals(picks: list[dict]) -> list[dict]:
    """Return reviewed finals only for exact event ID, clubs and kickoff day."""
    from leagues.results_checker import _normalize_name

    by_id = {item["sportybet_event_id"]: item for item in _VERIFIED_FINALS}
    matched: list[dict] = []
    for pick in picks:
        event_id = str(pick.get("sportybet_event_id") or "")
        verified = by_id.get(event_id)
        if not verified:
            continue
        kickoff = pick.get("commence_time") or pick.get("kickoff") or ""
        try:
            parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            continue
        date = parsed.astimezone(timezone.utc).date().isoformat()
        if (date != verified["date"]
                or _normalize_name(pick.get("home_team") or "") != _normalize_name(verified["home"])
                or _normalize_name(pick.get("away_team") or "") != _normalize_name(verified["away"])):
            continue
        matched.append({
            **verified,
            "completed": True,
            "provider": "verified-official-fixture-report",
            "provider_event_id": event_id,
            "match_status": "STATUS_FULL_TIME",
            "score_90": {"home": verified["home_score"], "away": verified["away_score"]},
        })
    return matched
