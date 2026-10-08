"""Strict input contract for a future commercially permissioned FT challenger.

Never imports the historical 64k-row corpus automatically: its row-level
license/odds provenance is unresolved. All features must be explicitly
whitelisted pre-kickoff quantities with an earlier capture timestamp.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
from pathlib import Path

from leagues.goal_distribution_challenger import settlement_labels

FEATURES = (
    "home_scored_avg_5", "home_conceded_avg_5",
    "away_scored_avg_5", "away_conceded_avg_5",
    "home_win_rate_5", "away_win_rate_5",
    "home_rating_pre", "away_rating_pre",
)
RIGHTS_BASES = {"OWNED_VERIFIED", "COMMERCIAL_LICENSE_VERIFIED",
                 "PUBLIC_DOMAIN_VERIFIED"}
MIN_TRAIN_ROWS = 500


def _datetime(value: str, name: str) -> dt.datetime:
    try:
        result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        raise ValueError(f"{name} requires timezone-aware ISO timestamp") from None


def validate_records(records: list[dict]) -> list[dict]:
    if not records:
        raise ValueError("No training records provided")
    seen: set[str] = set()
    ready = []
    for pos, original in enumerate(records, 1):
        row = dict(original)
        identity = str(row.get("fixture_id") or "").strip()
        if not identity or identity in seen:
            raise ValueError(f"Row {pos}: fixture identity missing or duplicated")
        seen.add(identity)
        if row.get("rights_basis") not in RIGHTS_BASES:
            raise ValueError(f"Row {pos}: verified commercial training rights required")
        for field in ("source_id", "license_reference", "rights_verified_by"):
            if not str(row.get(field) or "").strip():
                raise ValueError(f"Row {pos}: missing {field} provenance")
        kickoff = _datetime(row.get("kickoff_utc"), "kickoff_utc")
        features_at = _datetime(row.get("features_as_of_utc"), "features_as_of_utc")
        if not features_at < kickoff:
            raise ValueError(f"Row {pos}: pre-match feature timing leakage")
        try:
            home = int(str(row["home_goals"]))
            away = int(str(row["away_goals"]))
            if str(home) != str(row["home_goals"]).strip() or str(away) != str(row["away_goals"]).strip():
                raise ValueError()
            labels = settlement_labels(home, away)
        except (ValueError, TypeError, KeyError):
            raise ValueError(f"Row {pos}: invalid settled score") from None
        values = []
        for field in FEATURES:
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"Row {pos}: missing or invalid feature {field}") from None
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Row {pos}: invalid pre-match feature {field}")
            if field.endswith("_rate_5") and value > 1:
                raise ValueError(f"Row {pos}: invalid win rate {field}")
            values.append(value)
        ready.append({
            "fixture_id": identity,
            "kickoff_utc": kickoff,
            "source_id": row["source_id"],
            "rights_basis": row["rights_basis"],
            "feature_vector": values,
            "home_goals": home,
            "away_goals": away,
            "labels": labels,
        })
    return sorted(ready, key=lambda x: (x["kickoff_utc"], x["fixture_id"]))


def read_permissioned_csv(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Training CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return validate_records(rows)


def chronological_groups(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split by WHOLE WAT calendar days, never splitting one date across sets."""
    if len(records) < MIN_TRAIN_ROWS:
        raise ValueError(f"Need at least {MIN_TRAIN_ROWS} permissioned training fixtures")
    days = sorted({(r["kickoff_utc"] + dt.timedelta(hours=1)).date() for r in records})
    if len(days) < 30:
        raise ValueError("At least 30 distinct football calendar dates required")
    train_end = max(1, int(len(days) * .70))
    calibration_end = max(train_end + 1, int(len(days) * .85))
    if calibration_end >= len(days):
        raise ValueError("Not enough chronological dates for holdout")
    train_days = set(days[:train_end])
    calib_days = set(days[train_end:calibration_end])
    test_days = set(days[calibration_end:])
    parts = tuple([
        r for r in records
        if (r["kickoff_utc"] + dt.timedelta(hours=1)).date() in group
    ] for group in (train_days, calib_days, test_days))
    if not all(parts):
        raise ValueError("Empty chronological train/calibration/test segment")
    return parts
