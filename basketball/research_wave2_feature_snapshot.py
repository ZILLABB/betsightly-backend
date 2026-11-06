"""Immutable, pre-tipoff NBA Wave 2 model-input snapshot.

Use only the *same* feature vector passed into the frozen shadow model.
Never reconstruct snapshots for previously signed forecast records.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

from basketball.research_advanced_features import (
    FEATURE_COLUMNS, VERSION,
)
from basketball.research_features import FEATURE_COLUMNS as V1_FEATURES

SNAPSHOT_VERSION = "nba-wave2-frozen-feature-vector-v1"
assert tuple(FEATURE_COLUMNS[:len(V1_FEATURES)]) == tuple(V1_FEATURES)


def _utc(text):
    if not isinstance(text, str):
        raise ValueError("invalid_feature_snapshot_timestamp")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid_feature_snapshot_timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive_feature_snapshot_timestamp")
    return dt.astimezone(timezone.utc)


def _fingerprint(columns, values):
    encoded = json.dumps({"columns": columns, "values": values},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_feature_snapshot(*, vector, captured_at, tipoff_at):
    """Embed original per-feature model inputs into new append-only records."""
    captured = _utc(captured_at)
    start = _utc(tipoff_at)
    if captured >= start:
        raise ValueError("feature_snapshot_not_before_tipoff")
    if len(vector) != len(FEATURE_COLUMNS):
        raise ValueError("feature_snapshot_wrong_vector_length")
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           for x in vector):
        raise ValueError("feature_snapshot_non_numeric")
    values = [float(x) for x in vector]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("feature_snapshot_nonfinite")
    columns = list(FEATURE_COLUMNS)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "feature_schema": VERSION,
        "captured_at": captured_at,
        "columns": columns,
        "values": values,
        "matched_v1_prefix_count": len(V1_FEATURES),
        "vector_sha256": _fingerprint(columns, values),
    }


def validate_feature_snapshot(row):
    """Legacy snapshots remain absent; new signed records fail closed."""
    snapshot = row.get("pregame_feature_snapshot")
    if snapshot is None:
        if "pregame_feature_snapshot" in row:
            raise ValueError("feature_snapshot_explicit_null")
        return False
    if not isinstance(snapshot, dict):
        raise ValueError("feature_snapshot_not_object")
    if (snapshot.get("snapshot_version") != SNAPSHOT_VERSION or
            snapshot.get("feature_schema") != VERSION or
            row.get("source_feature_schema") != VERSION or
            snapshot.get("matched_v1_prefix_count") != len(V1_FEATURES)):
        raise ValueError("feature_snapshot_schema_mismatch")
    columns, values = snapshot.get("columns"), snapshot.get("values")
    if (not isinstance(columns, list) or columns != list(FEATURE_COLUMNS)
            or not isinstance(values, list)
            or len(values) != len(FEATURE_COLUMNS)):
        raise ValueError("feature_snapshot_invalid_columns_or_length")
    if any(isinstance(x, bool) or not isinstance(x, (int,float))
           or not math.isfinite(x) for x in values):
        raise ValueError("feature_snapshot_invalid_numeric_values")
    if (not isinstance(snapshot.get("captured_at"), str) or
            _utc(snapshot["captured_at"]) != _utc(row["created_at"]) or
            _utc(snapshot["captured_at"]) >= _utc(row["start_utc"])):
        raise ValueError("feature_snapshot_time_mismatch")
    if snapshot.get("vector_sha256") != _fingerprint(columns, values):
        raise ValueError("feature_snapshot_fingerprint_mismatch")
    return True
