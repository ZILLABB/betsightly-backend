"""Provenance-first historical match warehouse utilities.

The warehouse is deliberately separate from the legacy runtime CSV.  It gives
future training/replay jobs a stable match identity, explicit row provenance,
explicit odds provenance, and deterministic duplicate handling.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

TRAINING_COLUMNS = [
    "home_team", "away_team", "date",
    "home_score", "away_score",
    "ht_home_score", "ht_away_score",
    "league_id", "league_name", "country", "league_tier", "season",
    "home_team_id", "away_team_id",
    "avg_odds_home", "avg_odds_draw", "avg_odds_away",
    "avg_odds_over25", "avg_odds_under25",
]

PROVENANCE_COLUMNS = [
    "historical_match_id",
    "source_provider",
    "source_dataset",
    "source_url",
    "source_file",
    "source_row_id",
    "source_league_code",
    "provenance_quality",
    "fetched_at",
    "odds_home_source_column",
    "odds_draw_source_column",
    "odds_away_source_column",
    "odds_over25_source_column",
    "odds_under25_source_column",
    "odds_home_snapshot_type",
    "odds_draw_snapshot_type",
    "odds_away_snapshot_type",
    "odds_over25_snapshot_type",
    "odds_under25_snapshot_type",
]

WAREHOUSE_COLUMNS = TRAINING_COLUMNS + PROVENANCE_COLUMNS


def normalize_identity(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _clean(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _int_or_blank(value):
    text = _clean(value)
    if not text:
        return ""
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return ""


def _float_or_blank(value):
    text = _clean(value)
    if not text:
        return ""
    try:
        value = float(text)
        return value if math.isfinite(value) and value > 1.0 else ""
    except (TypeError, ValueError):
        return ""


def stable_match_id(row: dict) -> str:
    """Stable fixture identity independent of result or bookmaker price."""
    material = "|".join([
        normalize_identity(row.get("country") or ""),
        _clean(row.get("league_id")),
        normalize_identity(row.get("league_name") or ""),
        _clean(row.get("date")),
        normalize_identity(row.get("home_team") or ""),
        normalize_identity(row.get("away_team") or ""),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def identity_key(row: dict) -> tuple[str, str, str, str, str, str]:
    return (
        normalize_identity(row.get("country") or ""),
        _clean(row.get("league_id")),
        normalize_identity(row.get("league_name") or ""),
        _clean(row.get("date")),
        normalize_identity(row.get("home_team") or ""),
        normalize_identity(row.get("away_team") or ""),
    )


def score_key(row: dict) -> tuple:
    return (
        _int_or_blank(row.get("home_score")),
        _int_or_blank(row.get("away_score")),
    )


def _legacy_source(input_path: Path) -> dict:
    # This is intentionally marked inferred: existing rows lack row-level
    # source metadata, so the path/script history is not proof of each row.
    path = input_path.as_posix().casefold()
    if "api-football/matches.csv" in path:
        return {
            "source_provider": "football-data.co.uk",
            "source_dataset": "legacy_training_csv",
            "source_url": "",
            "source_file": input_path.as_posix(),
            "provenance_quality": "LEGACY_INFERRED",
        }
    return {
        "source_provider": "unknown",
        "source_dataset": "legacy_training_csv",
        "source_url": "",
        "source_file": input_path.as_posix(),
        "provenance_quality": "LEGACY_INFERRED",
    }


def normalize_row(raw: dict, *, input_path: Path, row_number: int) -> dict | None:
    home = _clean(raw.get("home_team"))
    away = _clean(raw.get("away_team"))
    date = pd.to_datetime(raw.get("date"), errors="coerce")
    hs = _int_or_blank(raw.get("home_score"))
    aws = _int_or_blank(raw.get("away_score"))
    if not home or not away or pd.isna(date) or hs == "" or aws == "":
        return None

    legacy = _legacy_source(input_path)
    row = {col: "" for col in WAREHOUSE_COLUMNS}
    for col in TRAINING_COLUMNS:
        row[col] = raw.get(col, "")

    row.update({
        "home_team": home,
        "away_team": away,
        "date": date.date().isoformat(),
        "home_score": hs,
        "away_score": aws,
        "ht_home_score": _int_or_blank(raw.get("ht_home_score")),
        "ht_away_score": _int_or_blank(raw.get("ht_away_score")),
        "league_id": _int_or_blank(raw.get("league_id")),
        "league_name": _clean(raw.get("league_name")),
        "country": _clean(raw.get("country")),
        "league_tier": _int_or_blank(raw.get("league_tier")) or 1,
        "season": _clean(raw.get("season")),
        "home_team_id": _clean(raw.get("home_team_id")),
        "away_team_id": _clean(raw.get("away_team_id")),
        "avg_odds_home": _float_or_blank(raw.get("avg_odds_home")),
        "avg_odds_draw": _float_or_blank(raw.get("avg_odds_draw")),
        "avg_odds_away": _float_or_blank(raw.get("avg_odds_away")),
        "avg_odds_over25": _float_or_blank(raw.get("avg_odds_over25")),
        "avg_odds_under25": _float_or_blank(raw.get("avg_odds_under25")),
    })

    # Prefer exact raw provenance when the v2 fetcher supplied it.
    for col in PROVENANCE_COLUMNS:
        if col == "historical_match_id":
            continue
        if _clean(raw.get(col)):
            row[col] = _clean(raw.get(col))

    if not row["source_provider"]:
        row.update(legacy)
    elif not row["provenance_quality"]:
        row["provenance_quality"] = "EXACT_SOURCE_ROW"

    row["source_row_id"] = (
        _clean(raw.get("source_row_id"))
        or str(row_number)
    )
    row["source_file"] = row["source_file"] or input_path.as_posix()
    row["historical_match_id"] = stable_match_id(row)

    # Legacy rows do not preserve which source price column won. Never invent
    # opening/closing semantics for them.
    for market in ("home", "draw", "away", "over25", "under25"):
        source_col = f"odds_{market}_source_column"
        snap_col = f"odds_{market}_snapshot_type"
        if not row[source_col] and not row[snap_col]:
            row[snap_col] = "UNKNOWN_LEGACY_MIXED"

    return row


@dataclass
class WarehouseStats:
    input_rows: int = 0
    normalized_rows: int = 0
    rejected_rows: int = 0
    duplicate_rows: int = 0
    duplicate_keys: int = 0
    conflicting_keys: int = 0
    quarantined_rows: int = 0
    output_rows: int = 0
    exact_provenance_rows: int = 0
    inferred_provenance_rows: int = 0


def build_rows(frame: pd.DataFrame, *, input_path: Path):
    stats = WarehouseStats(input_rows=len(frame))
    grouped: dict[tuple, list[dict]] = {}

    for idx, raw in enumerate(frame.to_dict("records")):
        row = normalize_row(raw, input_path=input_path, row_number=idx)
        if row is None:
            stats.rejected_rows += 1
            continue
        stats.normalized_rows += 1
        if row["provenance_quality"] == "EXACT_SOURCE_ROW":
            stats.exact_provenance_rows += 1
        else:
            stats.inferred_provenance_rows += 1
        grouped.setdefault(identity_key(row), []).append(row)

    output: list[dict] = []
    quarantine: list[dict] = []

    for key in sorted(grouped):
        rows = grouped[key]
        if len(rows) == 1:
            output.append(rows[0])
            continue

        stats.duplicate_keys += 1
        stats.duplicate_rows += len(rows)

        scores = {score_key(row) for row in rows}
        if len(scores) > 1:
            stats.conflicting_keys += 1
            stats.quarantined_rows += len(rows)
            for row in rows:
                q = dict(row)
                q["quarantine_reason"] = "CONFLICTING_FINAL_SCORE"
                quarantine.append(q)
            continue

        # Deterministically prefer exact provenance, then richer odds, then
        # lower source_row_id. Missing odds may be filled only from an exact
        # duplicate with the same fixture/result identity.
        def quality(row):
            odds = sum(
                bool(row.get(col))
                for col in (
                    "avg_odds_home", "avg_odds_draw", "avg_odds_away",
                    "avg_odds_over25", "avg_odds_under25",
                )
            )
            exact = int(row.get("provenance_quality") == "EXACT_SOURCE_ROW")
            try:
                source_row = -int(row.get("source_row_id") or 0)
            except ValueError:
                source_row = 0
            return exact, odds, source_row

        winner = max(rows, key=quality).copy()
        for other in rows:
            if other is winner:
                continue
            for col in (
                "avg_odds_home", "avg_odds_draw", "avg_odds_away",
                "avg_odds_over25", "avg_odds_under25",
            ):
                if not winner.get(col) and other.get(col):
                    winner[col] = other[col]
        output.append(winner)

    output.sort(
        key=lambda row: (
            row["date"],
            row["historical_match_id"],
        )
    )
    stats.output_rows = len(output)
    return output, quarantine, stats


def build_manifest(
    rows: list[dict],
    quarantine: list[dict],
    stats: WarehouseStats,
    *,
    input_path: Path,
) -> dict:
    dates = [row["date"] for row in rows]
    league_ids = sorted({
        int(row["league_id"])
        for row in rows
        if str(row.get("league_id") or "").isdigit()
    })
    source_counts = Counter(row.get("source_provider") or "unknown" for row in rows)
    provenance_counts = Counter(
        row.get("provenance_quality") or "unknown" for row in rows
    )

    def complete(cols):
        return sum(all(bool(row.get(col)) for col in cols) for row in rows)

    one = complete(["avg_odds_home", "avg_odds_draw", "avg_odds_away"])
    ou = complete(["avg_odds_over25", "avg_odds_under25"])
    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_input": input_path.as_posix(),
        "stats": asdict(stats),
        "date_range": [min(dates), max(dates)] if dates else [None, None],
        "league_ids": league_ids,
        "source_counts": dict(source_counts),
        "provenance_quality_counts": dict(provenance_counts),
        "odds_coverage": {
            "complete_1x2_rows": one,
            "complete_1x2_pct": round(one / len(rows) * 100, 4) if rows else 0.0,
            "complete_ou25_rows": ou,
            "complete_ou25_pct": round(ou / len(rows) * 100, 4) if rows else 0.0,
        },
        "quarantine_count": len(quarantine),
        "training_columns": TRAINING_COLUMNS,
        "provenance_columns": PROVENANCE_COLUMNS,
    }


def write_warehouse(
    rows: list[dict],
    quarantine: list[dict],
    manifest: dict,
    *,
    output_csv: Path,
    quarantine_csv: Path,
    manifest_json: Path,
) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    quarantine_csv.parent.mkdir(parents=True, exist_ok=True)
    manifest_json.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(rows, columns=WAREHOUSE_COLUMNS).to_csv(
        output_csv, index=False
    )
    if quarantine:
        pd.DataFrame(quarantine).to_csv(quarantine_csv, index=False)
    elif quarantine_csv.exists():
        quarantine_csv.unlink()

    manifest_json.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
