"""Versioned, hash-verifiable ML artifact manifest generation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from leagues.feature_contract import FEATURE_SCHEMA_VERSION


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(model_dir: Path, meta: dict, *, data_start: str,
                   data_end: str, training_cutoff: str,
                   validation_cutoff: str,
                   activation_status: str = "READY_FOR_STAGING_VALIDATION") -> dict:
    families = ("xgb", "lgbm", "catboost", "rf", "et", "nn")
    files = sorted(
        path for path in model_dir.iterdir()
        if path.is_file() and path.suffix in {".joblib", ".json"}
        and path.name != "manifest.json"
    )
    return {
        "manifest_version": "1",
        "model_set_version": (
            f"api-football-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        ),
        "activation_status": activation_status,
        "trained_at": meta.get("trained_at"),
        "training_data_start": data_start,
        "training_data_end": data_end,
        "training_cutoff": training_cutoff,
        "validation_cutoff": validation_cutoff,
        "validation": "chronological train/calibration/test",
        "n_samples": meta.get("n_samples"),
        "artifact_feature_schema_version": FEATURE_SCHEMA_VERSION,
        "required_runtime_feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_compatible": True,
        "families": list(families),
        "targets": meta.get("ensemble") or {},
        "files": {path.name: sha256(path) for path in files},
    }
