"""Private four-table basketball research recovery, separate from NBA V2.

No data acquisition or public APIs. This is an integrity-checked full copy of
licensing metadata, approved historical finals and source-health receipts.
SHA-256 provides corruption detection, not authenticated provenance.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import text
from basketball.research_coldstart import _json
from basketball.research_multileague_release_gates import CANDIDATE_LEAGUES
from database import SessionLocal

VERSION = "betsightly-basketball-private-licensed-history-v1"
MAX_ROWS_PER_TABLE = 75_000
MAX_RAW_BYTES = 40_000_000
HEX = re.compile(r"^[0-9a-f]{64}$")
SCOPES = {
    "rights": ("basketball_data_rights", (
        "id", "league", "provider", "status", "evidence_sha256",
        "licensed_storage", "licensed_training", "licensed_betting_use",
        "licensed_redistribution", "approved_at", "expires_at", "created_at")),
    "imports": ("basketball_licensed_imports", (
        "id", "rights_id", "league", "provider", "season_code", "manifest_sha256",
        "event_count", "imported_at", "independent_score_agreement_verified",
        "model_approved", "public_publishing_enabled")),
    "games": ("basketball_licensed_games", (
        "id", "import_id", "league", "provider", "provider_event_id",
        "season_code", "tipoff_utc", "home_team_id", "away_team_id",
        "status", "home_score", "away_score", "row_sha256", "inserted_at")),
    "probes": ("nba_league_source_probes", (
        "id", "league", "provider", "scope_key", "recorded_at", "http_status",
        "events_observed", "identity_complete", "parsed_final_count",
        "source_page_complete", "commercial_use_cleared", "source_probe_only")),
}
TIME_FIELDS = frozenset({
    "approved_at", "expires_at", "created_at", "imported_at",
    "tipoff_utc", "inserted_at", "recorded_at",
})
BOOLEANS = frozenset({
    "licensed_storage", "licensed_training", "licensed_betting_use",
    "licensed_redistribution", "independent_score_agreement_verified",
    "model_approved", "public_publishing_enabled", "source_page_complete",
    "commercial_use_cleared", "source_probe_only",
})
NUMBERS = frozenset({
    "id", "rights_id", "import_id", "event_count", "home_score",
    "away_score", "http_status", "events_observed", "identity_complete",
    "parsed_final_count",
})


def _time(v):
    if isinstance(v, datetime):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("BASKETBALL_BACKUP_UNAWARE_TIME")
        return v.astimezone(timezone.utc).isoformat()
    if not isinstance(v, str):
        raise ValueError("BASKETBALL_BACKUP_BAD_TIME")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("BASKETBALL_BACKUP_BAD_TIME") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("BASKETBALL_BACKUP_UNAWARE_TIME")
    return d.astimezone(timezone.utc).isoformat()


def _validate_rows(rows):
    if not isinstance(rows, dict) or set(rows) != set(SCOPES):
        raise ValueError("BASKETBALL_BACKUP_SCOPE_INVALID")
    rights = {}
    imports = {}
    provider_games = set()
    for key, (_, columns) in SCOPES.items():
        table = rows[key]
        if not isinstance(table, list) or len(table) > MAX_ROWS_PER_TABLE:
            raise ValueError("BASKETBALL_BACKUP_ROW_LIMIT")
        last = 0
        for row in table:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError("BASKETBALL_BACKUP_ROW_SCHEMA_INVALID")
            if type(row["id"]) is not int or row["id"] <= last:
                raise ValueError("BASKETBALL_BACKUP_ID_ORDER_INVALID")
            last = row["id"]
            if row["league"] not in CANDIDATE_LEAGUES or not (
                isinstance(row["provider"], str) and
                re.fullmatch(r"[a-z][a-z0-9_]{2,50}", row["provider"])
            ):
                raise ValueError("BASKETBALL_BACKUP_LEAGUE_PROVIDER_INVALID")
            for field in columns:
                value = row[field]
                if field in TIME_FIELDS:
                    if value is not None:
                        _time(value)
                    elif field != "expires_at":
                        raise ValueError("BASKETBALL_BACKUP_MISSING_TIME")
                elif field in BOOLEANS and type(value) is not bool:
                    raise ValueError("BASKETBALL_BACKUP_BOOL_INVALID")
                elif field in NUMBERS and value is not None and (
                    type(value) is not int or value < 0 or value > 1000000000
                ):
                    raise ValueError("BASKETBALL_BACKUP_INT_INVALID")
                elif field not in BOOLEANS | NUMBERS | TIME_FIELDS and (
                    not isinstance(value, str) or not value
                    or len(value) > 128
                ):
                    raise ValueError("BASKETBALL_BACKUP_TEXT_INVALID")
            if key == "rights":
                if (row["status"] not in ("verified", "revoked", "expired") or
                    not HEX.fullmatch(row["evidence_sha256"])):
                    raise ValueError("BASKETBALL_BACKUP_RIGHTS_INVALID")
                rights[row["id"]] = row
            if key == "imports":
                if (row["rights_id"] not in rights or
                    not HEX.fullmatch(row["manifest_sha256"]) or
                    row["model_approved"] or row["public_publishing_enabled"]):
                    raise ValueError("BASKETBALL_BACKUP_IMPORT_INVALID")
                source = rights[row["rights_id"]]
                if (source["league"], source["provider"]) != (
                    row["league"], row["provider"]
                ):
                    raise ValueError("BASKETBALL_BACKUP_RIGHTS_IDENTITY_CONFLICT")
                imports[row["id"]] = row
            if key == "games":
                parent = imports.get(row["import_id"])
                if parent is None or (
                    parent["league"], parent["provider"], parent["season_code"]
                ) != (row["league"], row["provider"], row["season_code"]):
                    raise ValueError("BASKETBALL_BACKUP_GAME_SCOPE_INVALID")
                identity = (row["league"], row["provider"], row["provider_event_id"])
                if identity in provider_games or not HEX.fullmatch(row["row_sha256"]):
                    raise ValueError("BASKETBALL_BACKUP_GAME_ID_INVALID")
                provider_games.add(identity)
                if (row["status"] != "final" or
                    type(row["home_score"]) is not int or
                    type(row["away_score"]) is not int or
                    row["home_score"] == row["away_score"]):
                    raise ValueError("BASKETBALL_BACKUP_FINAL_INVALID")
            if key == "probes":
                if (row["commercial_use_cleared"] is not False or
                    row["source_probe_only"] is not True or
                    row["http_status"] != 200 or
                    row["parsed_final_count"] > row["identity_complete"] or
                    row["identity_complete"] > row["events_observed"]):
                    raise ValueError("BASKETBALL_BACKUP_PROBE_SCOPE_INVALID")
    for parent in imports.values():
        count = sum(g["import_id"] == parent["id"] for g in rows["games"])
        if count != parent["event_count"]:
            raise ValueError("BASKETBALL_BACKUP_MANIFEST_COUNT_MISMATCH")


def verify_history_recovery(envelope):
    if not isinstance(envelope, dict) or set(envelope) != {
        "version", "created_at", "tables", "counts", "research_only",
        "not_bookable", "sha256", "tables_sha256"
    } or envelope["version"] != VERSION or (
        envelope["research_only"] is not True or
        envelope["not_bookable"] is not True
    ):
        raise ValueError("BASKETBALL_BACKUP_ENVELOPE_INVALID")
    if len(_json(envelope).encode("utf-8")) > MAX_RAW_BYTES:
        raise ValueError("BASKETBALL_BACKUP_TOO_LARGE")
    _time(envelope["created_at"])
    _validate_rows(envelope["tables"])
    expected_tables = hashlib.sha256(_json(envelope["tables"]).encode("utf-8")).hexdigest()
    if envelope["tables_sha256"] != expected_tables:
        raise ValueError("BASKETBALL_BACKUP_TABLE_HASH_MISMATCH")
    counts = {k: len(v) for k,v in envelope["tables"].items()}
    if envelope["counts"] != counts:
        raise ValueError("BASKETBALL_BACKUP_COUNT_MISMATCH")
    canonical = {k:v for k,v in envelope.items() if k!="sha256"}
    digest = hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()
    if envelope["sha256"] != digest:
        raise ValueError("BASKETBALL_BACKUP_SHA_MISMATCH")
    return {"status":"history_recovery_envelope_verified",
            "counts":counts,"sha256":digest,"research_only":True,
            "not_bookable":True,"independent_restore_proven":False}


def build_history_recovery(*, session_factory=None):
    """Read-only snapshot of all four explicitly authorized staging tables."""
    with (session_factory or SessionLocal)() as db:
        data = {}
        for key, (table, columns) in SCOPES.items():
            query = "SELECT " + ",".join(columns) + (
                f" FROM nba_research.{table} ORDER BY id"
            )
            saved = db.execute(text(query)).mappings().all()
            if len(saved) > MAX_ROWS_PER_TABLE:
                raise ValueError("BASKETBALL_BACKUP_ROW_LIMIT")
            data[key] = [{
                field: (_time(row[field]) if field in TIME_FIELDS and
                        row[field] is not None else row[field])
                for field in columns
            } for row in saved]
        _validate_rows(data)
        envelope = {
            "version":VERSION,
            "created_at":datetime.now(timezone.utc).isoformat(),
            "tables":data,
            "counts":{key:len(row) for key,row in data.items()},
            "tables_sha256":hashlib.sha256(_json(data).encode("utf-8")).hexdigest(),
            "research_only":True,
            "not_bookable":True,
        }
        envelope["sha256"]=hashlib.sha256(
            _json(envelope).encode("utf-8")
        ).hexdigest()
        verify_history_recovery(envelope)
        return envelope
