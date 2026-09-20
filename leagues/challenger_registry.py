"""Immutable champion/challenger metadata and evidence-based promotion checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import tempfile


REGISTRY_VERSION = "1"


@dataclass(frozen=True)
class PromotionPolicy:
    min_common_test_observations: int = 2000
    max_log_loss_regression: float = 0.002
    max_brier_regression: float = 0.002
    require_shadow_observations: int = 200


def artifact_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def promotion_assessment(challenger: dict, champion: dict | None,
                         policy: PromotionPolicy = PromotionPolicy()) -> dict:
    checks = {
        "feature_compatible": challenger.get("compatibility") == "COMPATIBLE",
        "data_quality_passed": challenger.get("data_quality") == "PASSED",
        "leakage_checks_passed": challenger.get("leakage_checks") == "PASSED",
        "calibration_passed": challenger.get("calibration_status") == "PASSED",
        "common_test_sample": int(challenger.get("common_test_n") or 0) >= policy.min_common_test_observations,
        "shadow_sample": int(challenger.get("shadow_n") or 0) >= policy.require_shadow_observations,
        "latency_acceptable": challenger.get("latency_status") == "PASSED",
        "startup_stable": challenger.get("startup_status") == "PASSED",
        "rollback_ready": bool(challenger.get("rollback_artifact")),
    }
    tradeoffs = []
    if champion:
        for metric, tolerance in (("log_loss", policy.max_log_loss_regression),
                                  ("brier", policy.max_brier_regression)):
            new = challenger.get(metric)
            old = champion.get(metric)
            ok = new is not None and old is not None and float(new) <= float(old) + tolerance
            checks[f"no_material_{metric}_regression"] = ok
            if ok and float(new) > float(old):
                tradeoffs.append(f"{metric}_within_tolerance_but_not_improved")
    approved = all(checks.values())
    return {
        "recommendation": "ELIGIBLE_FOR_HUMAN_REVIEW" if approved else "DO_NOT_PROMOTE",
        "automatic_promotion": False,
        "checks": checks,
        "tradeoffs": tradeoffs,
        "explicit_owner_approval_required": True,
    }


class ChallengerRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> dict:
        if not self.path.exists():
            return {"registry_version": REGISTRY_VERSION, "champion": None,
                    "challengers": [], "runs": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("registry_version") != REGISTRY_VERSION:
            raise ValueError("REGISTRY_VERSION_MISMATCH")
        return data

    def write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix="challenger-", suffix=".json",
                                             dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as temp:
                json.dump(data, temp, indent=2, sort_keys=True)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def register_challenger(self, record: dict) -> dict:
        data = self.read()
        version = str(record.get("model_version") or "")
        artifact = Path(str(record.get("artifact_path") or ""))
        if not version or not artifact.exists():
            raise ValueError("INVALID_CHALLENGER_RECORD")
        actual_hash = artifact_sha256(artifact)
        if record.get("artifact_sha256") != actual_hash:
            raise ValueError("ARTIFACT_HASH_MISMATCH")
        existing = next((item for item in data["challengers"]
                         if item.get("model_version") == version), None)
        if existing:
            if existing != record:
                raise ValueError("IMMUTABLE_CHALLENGER_CONFLICT")
            return existing
        data["challengers"].append(record)
        self.write(data)
        return record

    def record_run(self, run_key: str, record: dict) -> dict:
        data = self.read()
        if run_key in data["runs"]:
            return data["runs"][run_key]
        data["runs"][run_key] = record
        self.write(data)
        return record

    def promote(self, *_args, **_kwargs):
        raise PermissionError("AUTOMATIC_PROMOTION_DISABLED")
