"""Safe internal status for model compatibility and challenger operations."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

from leagues.challenger_registry import ChallengerRegistry
from leagues.weekly_training import proposed_schedule


def status() -> dict:
    from leagues.ml_models import status as market_aware_status

    registry_path = os.getenv("CHALLENGER_REGISTRY_PATH")
    registry = None
    if registry_path:
        try:
            registry = ChallengerRegistry(Path(registry_path)).read()
        except Exception as exc:
            registry = {"error": type(exc).__name__}
    market = market_aware_status()
    challengers = (registry or {}).get("challengers") or []
    latest = challengers[-1] if challengers else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_market_aware": {
            "available": market.get("available"),
            "feature_schema_version": market.get("feature_schema_version"),
            "compatibility": market.get("compatibility"),
            "trained_at": market.get("trained_at"),
        },
        "football_first": {
            "active": False,
            "active_model_version": None,
            "challenger_version": (latest or {}).get("model_version"),
            "dataset_cutoff": (latest or {}).get("dataset_cutoff"),
            "calibration_version": (latest or {}).get("calibration_version"),
            "latest_evaluation_status": (latest or {}).get("evaluation_status"),
            "compatibility": (latest or {}).get("compatibility") or "NO_REGISTERED_CHALLENGER",
        },
        "weekly_training": proposed_schedule(),
        "registry_configured": bool(registry_path),
        "registry_error": (registry or {}).get("error"),
        "production_auto_promotion": False,
    }
