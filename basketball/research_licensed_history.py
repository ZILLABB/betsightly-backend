"""Permission-gated, append-only historical fixtures for six non-NBA leagues.

Sources must come from an independently cleared licence. No HTTP fetch, scraping,
bookmaker code, or public basketball model is performed here. The DB license
record must explicitly allow storage, training, AND gambling-related use.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from sqlalchemy import text
from basketball.research_coldstart import _json
from basketball.research_multileague_release_gates import CANDIDATE_LEAGUES
from database import SessionLocal

MAX_GAME_BATCH = 1000
MAX_BYTES = 2_800_000
PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,50}$")
SEASON_PATTERN = re.compile(r"^[0-9]{4}(-[0-9]{2,4})?$")
ALLOWED_GAME_KEYS = frozenset({
    "provider_event_id", "tipoff_utc", "home_team_id", "away_team_id",
    "status", "home_score", "away_score",
})

def _check_ident(value, key: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or (
        not value.strip() or any(ord(ch) < 33 for ch in value)
    ):
        raise ValueError("BASKETBALL_HISTORY_INVALID_" + key)
    return value

def validate_history_batch(league, provider, season_code, games):
    if league not in CANDIDATE_LEAGUES or not isinstance(provider, str) or (
        not PROVIDER_PATTERN.fullmatch(provider)
    ):
        raise ValueError("BASKETBALL_HISTORY_LEAGUE_OR_PROVIDER_INVALID")
    if not isinstance(season_code, str) or not SEASON_PATTERN.fullmatch(season_code):
        raise ValueError("BASKETBALL_HISTORY_SEASON_INVALID")
    if not isinstance(games, list) or not 1 <= len(games) <= MAX_GAME_BATCH:
        raise ValueError("BASKETBALL_HISTORY_BATCH_COUNT_INVALID")
    if len(_json(games).encode("utf-8")) > MAX_BYTES:
        raise ValueError("BASKETBALL_HISTORY_BATCH_BYTES_EXCEEDED")
    normalized = []
    observed = set()
    for game in games:
        if not isinstance(game, dict) or set(game) != ALLOWED_GAME_KEYS:
            raise ValueError("BASKETBALL_HISTORY_ROW_SCHEMA_INVALID")
        event = _check_ident(game["provider_event_id"], "EVENT_ID")
        home = _check_ident(game["home_team_id"], "HOME_TEAM_ID")
        away = _check_ident(game["away_team_id"], "AWAY_TEAM_ID")
        if home == away or event in observed:
            raise ValueError("BASKETBALL_HISTORY_DUPLICATE_OR_SAME_TEAM")
        observed.add(event)
        try:
            ts = datetime.fromisoformat(game["tipoff_utc"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("BASKETBALL_HISTORY_TIPOFF_INVALID") from exc
        if ts.tzinfo is None or ts.utcoffset() is None or not (
            2000 <= ts.year <= 2040
        ):
            raise ValueError("BASKETBALL_HISTORY_TIPOFF_INVALID")
        state = game["status"]
        if state != "final":
            # Immutable historic training evidence, never a live scoreboard.
            raise ValueError("BASKETBALL_HISTORY_NONFINAL_WITHHELD")
        hs, az = game["home_score"], game["away_score"]
        if state == "final":
            if (type(hs) is not int or type(az) is not int or
                not 0 <= hs <= 400 or not 0 <= az <= 400 or hs == az):
                raise ValueError("BASKETBALL_HISTORY_FINAL_INVALID")
        elif hs is not None or az is not None:
            raise ValueError("BASKETBALL_HISTORY_UNSETTLED_SCORES_INVALID")
        row = {"provider_event_id": event, "tipoff_utc": ts.astimezone(
                   timezone.utc).isoformat(), "home_team_id":home,
               "away_team_id":away, "status":state,
               "home_score":hs, "away_score":az}
        row["row_sha256"] = hashlib.sha256(_json(row).encode()).hexdigest()
        normalized.append(row)
    normalized.sort(key=lambda item:item["provider_event_id"])
    manifest = {
        "league":league, "provider":provider,
        "season_code":season_code,
        "rows":normalized,
    }
    return normalized, hashlib.sha256(_json(manifest).encode()).hexdigest()

_FIND_RIGHTS = text("""
SELECT id FROM nba_research.basketball_data_rights
WHERE league=:league AND provider=:provider
AND status='verified' AND licensed_storage IS TRUE
AND licensed_training IS TRUE AND licensed_betting_use IS TRUE
AND approved_at<=now() AND (expires_at IS NULL OR expires_at>now())
ORDER BY approved_at DESC,id DESC LIMIT 1 FOR SHARE
""")

_INSERT_MANIFEST = text("""
INSERT INTO nba_research.basketball_licensed_imports
(rights_id,league,provider,season_code,manifest_sha256,event_count)
VALUES (:rights_id,:league,:provider,:season_code,:manifest_sha256,:event_count)
ON CONFLICT (manifest_sha256) DO NOTHING RETURNING id
""")

_INSERT_ROW = text("""
INSERT INTO nba_research.basketball_licensed_games
(import_id,league,provider,provider_event_id,season_code,tipoff_utc,
 home_team_id,away_team_id,status,home_score,away_score,row_sha256)
VALUES (:import_id,:league,:provider,:provider_event_id,:season_code,:tipoff_utc,
        :home_team_id,:away_team_id,:status,:home_score,:away_score,:row_sha256)
""")

def import_licensed_history(league, provider, season_code, games, *,
                            session_factory=None):
    """Never connect until full validation; never import without active grant."""
    rows, digest = validate_history_batch(league, provider, season_code, games)
    params = {"league":league,"provider":provider,"season_code":season_code,
              "manifest_sha256":digest, "event_count":len(rows)}
    with (session_factory or SessionLocal)() as db:
        try:
            # PostgreSQL transaction-scoped lock serializes cross-batch writes.
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                           {"key": 739155310002})
            rights_id=db.execute(_FIND_RIGHTS,params).scalar()
            if rights_id is None:
                raise ValueError("BASKETBALL_HISTORY_COMMERCIAL_RIGHTS_NOT_VERIFIED")
            params["rights_id"]=rights_id
            created=db.execute(_INSERT_MANIFEST,params).scalar()
            if created is None:
                saved=db.execute(text("""
                    SELECT id,league,provider,season_code,event_count
                    FROM nba_research.basketball_licensed_imports
                    WHERE manifest_sha256=:manifest_sha256
                """),params).mappings().one()
                if (saved["league"],saved["provider"],saved["season_code"],
                    saved["event_count"]) != (league,provider,season_code,len(rows)):
                    raise ValueError("BASKETBALL_HISTORY_MANIFEST_COLLISION")
                db.rollback()
                return {"status":"already_imported","league":league,
                        "count":len(rows),"manifest_sha256":digest,
                        "research_only":True,"not_bookable":True}
            batch = [{**row, "import_id":created, "league":league,
                      "provider":provider,"season_code":season_code}
                     for row in rows]
            db.execute(_INSERT_ROW,batch)
            stored=db.execute(text("""
                SELECT provider_event_id,row_sha256
                FROM nba_research.basketball_licensed_games
                WHERE import_id=:import_id ORDER BY provider_event_id
            """),{"import_id":created}).mappings().all()
            expected=[(row["provider_event_id"],row["row_sha256"]) for row in rows]
            actual=[(row["provider_event_id"],row["row_sha256"]) for row in stored]
            if actual != expected:
                raise ValueError("BASKETBALL_HISTORY_READBACK_HASH_MISMATCH")
            db.commit()
            return {"status":"licensed_history_saved","league":league,
                    "count":len(rows),"manifest_sha256":digest,
                    "source_rights_checked":True,
                    "research_only":True,"not_bookable":True,
                    "public_publishing_enabled":False}
        except Exception:
            db.rollback()
            raise

def history_readiness(*, session_factory=None):
    """Read-only exact DB counts; never turn rights evidence into model approval."""
    with (session_factory or SessionLocal)() as db:
        rights=db.execute(text("""
            SELECT league,COUNT(*) AS grants
            FROM nba_research.basketball_data_rights
            WHERE status='verified' AND licensed_storage IS TRUE
            AND licensed_training IS TRUE AND licensed_betting_use IS TRUE
            AND approved_at<=now() AND (expires_at IS NULL OR expires_at>now())
            GROUP BY league
        """)).mappings().all()
        counts=db.execute(text("""
            SELECT league,COUNT(DISTINCT season_code) AS seasons,
                   COUNT(*) AS games,
                   COUNT(*) FILTER (WHERE status='final') AS finals
            FROM nba_research.basketball_licensed_games GROUP BY league
        """)).mappings().all()
    grants={row["league"]:int(row["grants"]) for row in rights}
    data={row["league"]:row for row in counts}
    return {"status":"licensed_history_research_only",
            "leagues":[{
                "league":league, "active_commercial_data_grants":grants.get(league,0),
                "imported_games":int(data[league]["games"]) if league in data else 0,
                "imported_final_games":int(data[league]["finals"]) if league in data else 0,
                "observed_season_codes":int(data[league]["seasons"]) if league in data else 0,
                "complete_historical_seasons_verified":0,
                "independently_verified_final_scores":0,
                "approved_model":False,"public_publishing_enabled":False,
                "not_bookable":True,
            } for league in CANDIDATE_LEAGUES],
            "research_only":True,"not_bookable":True}
