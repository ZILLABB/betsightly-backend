"""Private Supabase metadata-only probes; never stores source games or odds.

The table is independently migrated into the nba_research schema, with RLS
enabled and no anon/authenticated grants. No raw team, player or score data.
"""
from __future__ import annotations

from sqlalchemy import text
from basketball.research_multileague_release_gates import CANDIDATE_LEAGUES
from basketball.research_league_source_catalog import SOURCES
from database import SessionLocal

_INSERT = text("""
INSERT INTO nba_research.nba_league_source_probes
(league,provider,scope_key,http_status,events_observed,identity_complete,
 parsed_final_count,source_page_complete,commercial_use_cleared,source_probe_only)
SELECT :league,:provider,:scope_key,200,:events,:identities,:finals,:complete,false,true
WHERE NOT EXISTS (
    SELECT 1 FROM nba_research.nba_league_source_probes
    WHERE league=:league AND scope_key=:scope_key
    AND events_observed=:events AND identity_complete=:identities
    AND parsed_final_count=:finals
    AND recorded_at > now() - interval '30 minutes'
)
""")

def record_probe(league: str, scope_key: str, report: dict, *, session_factory=None):
    """Append a bounded source-availability receipt; never replay raw records."""
    if league not in CANDIDATE_LEAGUES or not isinstance(report, dict):
        raise ValueError("BASKETBALL_SOURCE_PROBE_INVALID")
    if not isinstance(scope_key, str) or len(scope_key) not in (4, 8) or not scope_key.isdecimal():
        raise ValueError("BASKETBALL_SOURCE_PROBE_SCOPE_INVALID")
    if league in ("euroleague", "eurocup"):
        expected = {
            "events": report.get("season_total_claimed"),
            "identities": report.get("page_identities_checked"),
            "finals": 0,
            "complete": report.get("page_complete") is True,
        }
    else:
        expected = {
            "events": report.get("events_observed"),
            "identities": report.get("identity_complete_fixtures"),
            "finals": report.get("exact_completed"),
            "complete": False,  # One ESPN day is not an entire validated league season.
        }
    numbers = tuple(expected[key] for key in ("events", "identities", "finals"))
    if any(type(v) is not int for v in numbers) or not (
        0 <= expected["finals"] <= expected["identities"] <= expected["events"] <= 1000
    ):
        raise ValueError("BASKETBALL_SOURCE_PROBE_COUNTS_INVALID")
    params = {"league":league, "provider":SOURCES[league]["provider"],
              "scope_key":scope_key, **expected}
    with (session_factory or SessionLocal)() as db:
        db.execute(_INSERT, params)
        db.commit()
    return {"status":"private_source_metadata_recorded",
            "league":league,"source_probe_only":True,
            "commercial_use_cleared":False,"not_bookable":True}

def latest_probes(*, session_factory=None) -> dict:
    """Newest bounded metadata receipt for each of the six candidates."""
    with (session_factory or SessionLocal)() as db:
        rows=db.execute(text("""
            SELECT DISTINCT ON (league) league,provider,scope_key,recorded_at,
                   http_status,events_observed,identity_complete,
                   parsed_final_count,source_page_complete,
                   commercial_use_cleared
            FROM nba_research.nba_league_source_probes
            ORDER BY league,recorded_at DESC,id DESC
        """)).mappings().all()
    return {row["league"]:{
        "provider":row["provider"],"scope_key":row["scope_key"],
        "observed_at":row["recorded_at"].isoformat(),
        "http_status":row["http_status"],
        "events_observed":row["events_observed"],
        "identity_complete":row["identity_complete"],
        "parsed_final_count":row["parsed_final_count"],
        "source_page_complete":row["source_page_complete"],
        "commercial_use_cleared":row["commercial_use_cleared"],
        "independent_final_agreement":False,
    } for row in rows}
