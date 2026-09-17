"""Semantic versioning and readiness labels for public prediction policy."""

from __future__ import annotations


# This version identifies the complete public decision policy, not a deploy.
# Change it only when selection/calibration policy changes materially.
PUBLISHED_SELECTION_POLICY_VERSION = "selection-policy-v1.1"

# Current-policy evidence is blended with the historical cohort rather than
# switched on at an arbitrary sample threshold. Thirty observations gives the
# current cohort 50% influence; a tiny cohort remains strongly shrunk.
POLICY_PRIOR_STRENGTH = 30


def policy_weight(
    sample_size: int,
    prior_strength: int = POLICY_PRIOR_STRENGTH,
) -> float:
    sample = max(0, int(sample_size))
    return sample / (sample + max(1, int(prior_strength)))


def sample_readiness(sample_size: int) -> dict:
    sample = max(0, int(sample_size))
    bands = (
        (10, "VERY_THIN"),
        (30, "EARLY"),
        (50, "PROVISIONAL"),
        (100, "USABLE"),
        (200, "STRONG"),
    )
    for boundary, label in bands:
        if sample < boundary:
            return {"readiness": label, "next_readiness_at": boundary}
    return {"readiness": "MATURE", "next_readiness_at": None}
