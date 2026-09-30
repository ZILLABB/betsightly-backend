
"""Versioned runtime-only football-first shadow model.

The model is a second opinion only:
- it never changes predictor.predict()
- it never changes published confidence
- it never changes trust, selection, Builder, booking or settlement
- fixtures on/before the training cutoff fail closed

The artifact is produced by scripts/train_football_first_shadow.py from the
exact 15-feature runtime-core contract validated in Phase 7D.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

MODEL_DIR = Path(__file__).parent.parent / "models" / "football_first_shadow"
MODEL_PATH = MODEL_DIR / "match_result.joblib"
META_PATH = MODEL_DIR / "meta.json"

FEATURE_FLAG = "FOOTBALL_FIRST_SHADOW_ENABLED"
_STATE = {
    "loaded": False,
    "model": None,
    "meta": None,
}
_LOCK = threading.Lock()


def enabled() -> bool:
    value = str(
        os.getenv(
            FEATURE_FLAG,
            "false",
        )
    ).strip().lower()
    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


def artifact_available() -> bool:
    return (
        MODEL_PATH.exists()
        and META_PATH.exists()
    )


def reset_for_tests() -> None:
    with _LOCK:
        _STATE.update({
            "loaded": False,
            "model": None,
            "meta": None,
        })


def _load() -> dict:
    if _STATE["loaded"]:
        return _STATE

    with _LOCK:
        if _STATE["loaded"]:
            return _STATE

        try:
            import joblib

            meta = json.loads(
                META_PATH.read_text(
                    encoding="utf-8"
                )
            )
            model = joblib.load(
                MODEL_PATH
            )

            if (
                meta.get("feature_version")
                != "football-first-runtime-core-v1"
            ):
                raise ValueError(
                    "unsupported football-first feature version"
                )

            if (
                meta.get("target")
                != "match_result"
            ):
                raise ValueError(
                    "unexpected football-first target"
                )

            _STATE.update({
                "loaded": True,
                "model": model,
                "meta": meta,
            })

        except Exception:
            _STATE.update({
                "loaded": True,
                "model": None,
                "meta": None,
            })

    return _STATE


def _fixture_time(fixture: dict) -> datetime | None:
    raw = (
        fixture.get("commence_time")
        or fixture.get("kickoff")
    )
    if not raw:
        return None

    try:
        value = datetime.fromisoformat(
            str(raw).replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        return None

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _cutoff(meta: dict) -> datetime | None:
    raw = meta.get(
        "training_cutoff"
    )
    if not raw:
        return None

    try:
        value = datetime.fromisoformat(
            str(raw).replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        try:
            value = datetime.fromisoformat(
                str(raw)[:10]
                + "T23:59:59+00:00"
            )
        except ValueError:
            return None

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def predict_fixture(
    fixture: dict,
    history,
    *,
    require_enabled: bool = True,
) -> dict:
    """Return a prospective second opinion or a fail-closed status."""
    if (
        require_enabled
        and not enabled()
    ):
        return {
            "status": "DISABLED",
            "shadow_only": True,
        }

    state = _load()
    model = state.get("model")
    meta = state.get("meta") or {}

    if model is None or not meta:
        return {
            "status": "ARTIFACT_UNAVAILABLE",
            "shadow_only": True,
        }

    kickoff = _fixture_time(
        fixture
    )
    cutoff = _cutoff(
        meta
    )

    if kickoff is None:
        return {
            "status": "INVALID_KICKOFF",
            "shadow_only": True,
            "model_version": (
                meta.get(
                    "model_version"
                )
            ),
        }

    if (
        cutoff is None
        or kickoff <= cutoff
    ):
        return {
            "status": "TRAINING_OVERLAP",
            "shadow_only": True,
            "model_version": (
                meta.get(
                    "model_version"
                )
            ),
            "training_cutoff": (
                meta.get(
                    "training_cutoff"
                )
            ),
        }

    from leagues.football_first_runtime_core import (
        runtime_feature_vector,
    )

    prepared = runtime_feature_vector(
        fixture,
        history,
    )

    if (
        prepared.get("status")
        != "READY"
    ):
        return {
            **prepared,
            "shadow_only": True,
            "model_version": (
                meta.get(
                    "model_version"
                )
            ),
            "training_cutoff": (
                meta.get(
                    "training_cutoff"
                )
            ),
        }

    import numpy as np

    vector = np.asarray(
        [
            prepared["vector"]
        ],
        dtype=float,
    )

    raw = model.predict_proba(
        vector
    )[0]
    model_classes = list(
        model.classes_
    )

    probability_by_class = {
        int(value): float(
            raw[index]
        )
        for index, value in enumerate(
            model_classes
        )
    }

    probabilities = {
        "away_win": round(
            probability_by_class.get(
                0,
                0.0,
            ),
            6,
        ),
        "draw": round(
            probability_by_class.get(
                1,
                0.0,
            ),
            6,
        ),
        "home_win": round(
            probability_by_class.get(
                2,
                0.0,
            ),
            6,
        ),
    }

    total = sum(
        probabilities.values()
    )
    if total <= 0:
        return {
            "status": "INVALID_PROBABILITY",
            "shadow_only": True,
            "model_version": (
                meta.get(
                    "model_version"
                )
            ),
        }

    probabilities = {
        key: round(
            value / total,
            6,
        )
        for key, value in (
            probabilities.items()
        )
    }

    return {
        "status": "READY",
        "shadow_only": True,
        "publishable": False,
        "selection_changed": False,
        "probability_changed": False,
        "model_version": (
            meta.get(
                "model_version"
            )
        ),
        "feature_version": (
            meta.get(
                "feature_version"
            )
        ),
        "model_family": (
            meta.get(
                "selected_family"
            )
        ),
        "training_cutoff": (
            meta.get(
                "training_cutoff"
            )
        ),
        "trained_samples": (
            meta.get(
                "trained_samples"
            )
        ),
        "probabilities": (
            probabilities
        ),
        "feature_evidence": {
            "home_history": (
                prepared.get(
                    "home_history"
                )
            ),
            "away_history": (
                prepared.get(
                    "away_history"
                )
            ),
        },
    }


def market_probability(
    result: dict | None,
    market: str,
) -> float | None:
    if (
        not result
        or result.get("status")
        != "READY"
    ):
        return None

    values = (
        result.get(
            "probabilities"
        )
        or {}
    )

    if market in values:
        return float(
            values[market]
        )

    if market == "home_or_draw":
        if (
            "home_win" in values
            and "draw" in values
        ):
            return float(
                values["home_win"]
                + values["draw"]
            )

    if market == "away_or_draw":
        if (
            "away_win" in values
            and "draw" in values
        ):
            return float(
                values["away_win"]
                + values["draw"]
            )

    return None


def status() -> dict:
    state = _load()
    meta = state.get(
        "meta"
    ) or {}

    return {
        "enabled": enabled(),
        "artifact_available": bool(
            state.get("model")
        ),
        "model_version": (
            meta.get(
                "model_version"
            )
        ),
        "feature_version": (
            meta.get(
                "feature_version"
            )
        ),
        "target": (
            meta.get(
                "target"
            )
        ),
        "selected_family": (
            meta.get(
                "selected_family"
            )
        ),
        "training_cutoff": (
            meta.get(
                "training_cutoff"
            )
        ),
        "trained_samples": (
            meta.get(
                "trained_samples"
            )
        ),
        "shadow_only": True,
        "live_adjustment_allowed": False,
    }
