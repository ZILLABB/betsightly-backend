"""Independent football-first expected-goals challenger inference.

Artifacts are never discovered from the live model directory and never become
active automatically. Callers must pass an explicit registered challenger
path. The model outputs coherent probabilities from independently predicted
home/away scoring rates and contains no bookmaker inputs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from leagues.football_feature_contract import (
    FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, FootballFeatureVector,
)
from leagues.predictor import _outcome_probs, _p_over


ARTIFACT_FORMAT_VERSION = "football-first-artifact-v1"


class ScaledGoalRegressor:
    """Serializable calibration wrapper fitted only on the calibration era."""

    def __init__(self, estimator, scale: float):
        self.estimator = estimator
        self.scale = float(scale)

    def predict(self, rows):
        return self.estimator.predict(rows) * self.scale


def artifact_compatible(metadata: dict) -> tuple[bool, str]:
    if metadata.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
        return False, "ARTIFACT_FORMAT_VERSION_MISMATCH"
    if metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        return False, "FEATURE_SCHEMA_VERSION_MISMATCH"
    if tuple(metadata.get("feature_columns") or ()) != FEATURE_COLUMNS:
        return False, "FEATURE_COLUMN_ORDER_MISMATCH"
    if metadata.get("uses_bookmaker_features") is not False:
        return False, "BOOKMAKER_INDEPENDENCE_NOT_DECLARED"
    if metadata.get("promotion_status") not in {"CHALLENGER", "SHADOW", "CHAMPION"}:
        return False, "INVALID_PROMOTION_STATUS"
    return True, "COMPATIBLE"


def coherent_probabilities(home_lambda: float, away_lambda: float) -> dict[str, float]:
    home_lambda = max(0.05, min(float(home_lambda), 6.0))
    away_lambda = max(0.05, min(float(away_lambda), 6.0))
    ph, pd, pa = _outcome_probs(home_lambda, away_lambda)
    total = home_lambda + away_lambda
    over = {line: _p_over(line, total) for line in (1.5, 2.5, 3.5, 4.5)}
    btts = (1.0 - math.exp(-home_lambda)) * (1.0 - math.exp(-away_lambda))
    decisive = ph + pa
    values = {
        "home_win": ph, "draw": pd, "away_win": pa,
        "home_or_draw": ph + pd, "away_or_draw": pa + pd,
        "home_or_away": ph + pa,
        "dnb_home": ph / decisive if decisive else .5,
        "dnb_away": pa / decisive if decisive else .5,
        "over_1_5": over[1.5], "over_2_5": over[2.5],
        "over_3_5": over[3.5], "under_1_5": 1 - over[1.5],
        "under_2_5": 1 - over[2.5], "under_3_5": 1 - over[3.5],
        "under_4_5": 1 - over[4.5],
        "home_over_0_5": 1 - math.exp(-home_lambda),
        "away_over_0_5": 1 - math.exp(-away_lambda),
        "home_over_1_5": 1 - math.exp(-home_lambda) * (1 + home_lambda),
        "away_over_1_5": 1 - math.exp(-away_lambda) * (1 + away_lambda),
        "btts_yes": btts, "btts_no": 1 - btts,
    }
    return {name: round(max(0.0, min(1.0, value)), 6)
            for name, value in values.items()}


class FootballFirstChallenger:
    def __init__(self, artifact_path: str | Path):
        import joblib

        self.path = Path(artifact_path)
        payload = joblib.load(self.path)
        self.metadata = dict(payload.get("metadata") or {})
        compatible, reason = artifact_compatible(self.metadata)
        if not compatible:
            raise ValueError(reason)
        self.home_model = payload["home_goals_model"]
        self.away_model = payload["away_goals_model"]

    def predict(self, vector: FootballFeatureVector) -> dict[str, Any]:
        row = [vector.as_list()]
        home_lambda = float(self.home_model.predict(row)[0])
        away_lambda = float(self.away_model.predict(row)[0])
        return {
            "model_version": self.metadata["model_version"],
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "promotion_status": self.metadata["promotion_status"],
            "probabilities": coherent_probabilities(home_lambda, away_lambda),
            "expected_goals": {
                "home": round(max(.05, home_lambda), 4),
                "away": round(max(.05, away_lambda), 4),
                "total": round(max(.1, home_lambda + away_lambda), 4),
                "source": "football_first_model",
            },
            "uncertainty": self.metadata.get("uncertainty"),
            "as_of": vector.as_of,
            "missing_features": list(vector.missing),
            "bookmaker_independent": True,
        }


def metadata_from_path(path: str | Path) -> dict:
    sidecar = Path(path).with_suffix(".json")
    return json.loads(sidecar.read_text(encoding="utf-8"))
