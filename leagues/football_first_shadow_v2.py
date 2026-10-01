"""Prospective runtime-only V2 football-first shadow.

This model is observational only:
- never changes predictor.predict()
- never changes published probabilities
- never changes Builder/booking
- never changes settlement/public record
- only runs on the frozen V2 eligible-league allowlist
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

MODEL_DIR = (
    Path(__file__).parent.parent
    / "models"
    / "football_first_shadow_v2_candidate"
)
MODEL_PATH = MODEL_DIR / "match_result.joblib"
META_PATH = MODEL_DIR / "meta.json"

FEATURE_FLAG = "FOOTBALL_FIRST_SHADOW_V2_ENABLED"

_STATE = {
    "loaded": False,
    "model": None,
    "meta": None,
    "error": None,
}
_LOCK = threading.Lock()


def enabled() -> bool:
    return str(
        os.getenv(
            FEATURE_FLAG,
            "false",
        )
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


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
            "error": None,
        })


def _load() -> dict:
    if _STATE["loaded"]:
        return _STATE

    with _LOCK:
        if _STATE["loaded"]:
            return _STATE

        try:
            import joblib

            from leagues.football_first_runtime_v2 import (
                V2_CANDIDATE_FEATURE_COLUMNS,
                V2_CANDIDATE_VERSION,
            )

            meta = json.loads(
                META_PATH.read_text(
                    encoding="utf-8"
                )
            )

            if (
                meta.get("feature_version")
                != V2_CANDIDATE_VERSION
            ):
                raise ValueError(
                    "unsupported_v2_feature_version"
                )

            if (
                meta.get("target")
                != "match_result"
            ):
                raise ValueError(
                    "unexpected_v2_target"
                )

            if (
                list(
                    meta.get(
                        "feature_columns"
                    )
                    or []
                )
                != list(
                    V2_CANDIDATE_FEATURE_COLUMNS
                )
            ):
                raise ValueError(
                    "v2_feature_contract_mismatch"
                )

            if int(
                meta.get(
                    "feature_count"
                )
                or 0
            ) != 32:
                raise ValueError(
                    "unexpected_v2_feature_count"
                )

            expected_sha = str(
                (
                    meta.get("artifact")
                    or {}
                ).get("sha256")
                or ""
            )

            actual_sha = _sha256(
                MODEL_PATH
            )

            if (
                not expected_sha
                or actual_sha
                != expected_sha
            ):
                raise ValueError(
                    "v2_artifact_hash_mismatch"
                )

            if (
                meta.get(
                    "automatic_promotion"
                )
                is not False
            ):
                raise ValueError(
                    "v2_artifact_must_be_non_promoting"
                )

            model = joblib.load(
                MODEL_PATH
            )

            _STATE.update({
                "loaded": True,
                "model": model,
                "meta": meta,
                "error": None,
            })

        except Exception as exc:
            _STATE.update({
                "loaded": True,
                "model": None,
                "meta": None,
                "error": type(exc).__name__,
            })

    return _STATE


def _fixture_time(
    fixture: dict,
) -> datetime | None:

    raw = (
        fixture.get(
            "commence_time"
        )
        or fixture.get(
            "kickoff"
        )
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


def _cutoff(
    meta: dict,
) -> datetime | None:

    raw = meta.get(
        "training_cutoff"
    )

    if not raw:
        return None

    try:
        return datetime.fromisoformat(
            str(raw)[:10]
            + "T23:59:59+00:00"
        )
    except ValueError:
        return None


def predict_fixture(
    fixture: dict,
    history,
    cached_rates: dict,
    ratings: dict,
    *,
    require_enabled: bool = True,
) -> dict:

    if (
        require_enabled
        and not enabled()
    ):
        return {
            "status": "DISABLED",
            "shadow_only": True,
        }

    state = _load()

    model = state.get(
        "model"
    )

    meta = (
        state.get(
            "meta"
        )
        or {}
    )

    if model is None:
        return {
            "status":
                "ARTIFACT_UNAVAILABLE",
            "artifact_error":
                state.get(
                    "error"
                ),
            "shadow_only":
                True,
        }

    kickoff = _fixture_time(
        fixture
    )

    cutoff = _cutoff(
        meta
    )

    if kickoff is None:
        return {
            "status":
                "INVALID_KICKOFF",
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    if (
        cutoff is None
        or kickoff <= cutoff
    ):
        return {
            "status":
                "TRAINING_OVERLAP",
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
            "training_cutoff":
                meta.get(
                    "training_cutoff"
                ),
        }

    from leagues.football_first_runtime_elo import (
        ESPN_SLUG_TO_API_LEAGUE,
        runtime_elo_feature_vector,
    )
    from leagues.football_first_runtime_core import (
        runtime_feature_vector,
    )
    from leagues.football_first_runtime_v2 import (
        V2_CANDIDATE_FEATURE_COLUMNS,
        runtime_context_vector,
    )

    slug = str(
        fixture.get(
            "league_slug"
        )
        or ""
    )

    league_id = (
        ESPN_SLUG_TO_API_LEAGUE
        .get(
            slug
        )
    )

    eligible = {
        int(value)
        for value
        in (
            meta.get(
                "eligible_league_ids"
            )
            or []
        )
    }

    if (
        league_id is None
        or int(
            league_id
        )
        not in eligible
    ):
        return {
            "status":
                "UNSUPPORTED_LEAGUE",
            "league_slug":
                slug,
            "api_league_id":
                league_id,
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    core = runtime_feature_vector(
        fixture,
        history,
    )

    if (
        core.get(
            "status"
        )
        != "READY"
    ):
        return {
            **core,
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    elo = runtime_elo_feature_vector(
        fixture,
        ratings or {},
    )

    # UNAVAILABLE is a valid trained state:
    # runtime_elo_available=0 with neutral Elo values.
    if (
        elo.get(
            "status"
        )
        == "UNSUPPORTED_CONTEXT"
    ):
        return {
            **elo,
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    context = runtime_context_vector(
        fixture,
        history,
        cached_rates or {},
    )

    if (
        context.get(
            "status"
        )
        != "READY"
    ):
        return {
            **context,
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    features = {}

    features.update(
        core.get(
            "features"
        )
        or {}
    )

    features.update(
        elo.get(
            "features"
        )
        or {}
    )

    features.update(
        context.get(
            "features"
        )
        or {}
    )

    try:
        vector = [
            float(
                features[
                    column
                ]
            )
            for column
            in V2_CANDIDATE_FEATURE_COLUMNS
        ]
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return {
            "status":
                "FEATURE_VECTOR_INCOMPLETE",
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    if (
        len(
            vector
        )
        != 32
        or any(
            not math.isfinite(
                value
            )
            for value
            in vector
        )
    ):
        return {
            "status":
                "INVALID_FEATURE_VECTOR",
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    import numpy as np

    raw = model.predict_proba(
        np.asarray(
            [
                vector
            ],
            dtype=float,
        )
    )[0]

    classes = list(
        model.classes_
    )

    values = {
        int(
            value
        ): float(
            raw[
                index
            ]
        )
        for index, value
        in enumerate(
            classes
        )
    }

    probabilities = {
        "away_win":
            values.get(
                0,
                0.0,
            ),
        "draw":
            values.get(
                1,
                0.0,
            ),
        "home_win":
            values.get(
                2,
                0.0,
            ),
    }

    total = sum(
        probabilities.values()
    )

    if (
        not math.isfinite(
            total
        )
        or total <= 0
    ):
        return {
            "status":
                "INVALID_PROBABILITY",
            "shadow_only":
                True,
            "model_version":
                meta.get(
                    "model_version"
                ),
        }

    probabilities = {
        key: round(
            value / total,
            6,
        )
        for key, value
        in probabilities.items()
    }

    return {
        "status":
            "READY",

        "shadow_only":
            True,

        "publishable":
            False,

        "selection_changed":
            False,

        "probability_changed":
            False,

        "live_adjustment_allowed":
            False,

        "automatic_promotion":
            False,

        "model_version":
            meta.get(
                "model_version"
            ),

        "feature_version":
            meta.get(
                "feature_version"
            ),

        "model_family":
            meta.get(
                "selected_family"
            ),

        "training_cutoff":
            meta.get(
                "training_cutoff"
            ),

        "trained_samples":
            meta.get(
                "trained_samples"
            ),

        "feature_count":
            32,

        "api_league_id":
            int(
                league_id
            ),

        "probabilities":
            probabilities,

        "feature_evidence": {
            "home_history":
                core.get(
                    "home_history"
                ),

            "away_history":
                core.get(
                    "away_history"
                ),

            "elo_status":
                elo.get(
                    "status"
                ),

            "elo_rating_evidence":
                elo.get(
                    "rating_evidence"
                ),

            "base_sample_scaled":
                (
                    context.get(
                        "features"
                    )
                    or {}
                ).get(
                    "runtime_base_sample_scaled"
                ),
        },
    }


def status() -> dict:
    state = _load()

    meta = (
        state.get(
            "meta"
        )
        or {}
    )

    return {
        "enabled":
            enabled(),

        "artifact_available":
            bool(
                state.get(
                    "model"
                )
            ),

        "artifact_error":
            state.get(
                "error"
            ),

        "model_version":
            meta.get(
                "model_version"
            ),

        "feature_version":
            meta.get(
                "feature_version"
            ),

        "feature_count":
            meta.get(
                "feature_count"
            ),

        "selected_family":
            meta.get(
                "selected_family"
            ),

        "training_cutoff":
            meta.get(
                "training_cutoff"
            ),

        "trained_samples":
            meta.get(
                "trained_samples"
            ),

        "eligible_league_ids":
            meta.get(
                "eligible_league_ids"
            )
            or [],

        "shadow_only":
            True,

        "live_adjustment_allowed":
            False,

        "automatic_promotion":
            False,
    }
