"""Decision gate for SportyBet supplemental shadow candidates.

This module DOES NOT merge fixtures.

It asks whether shadow candidates have already satisfied BetSightly's existing
trust, evidence, market-floor, real-price and exact-bookability requirements.

Even an eligible result means only "safe to review for a staging-only
feature-flag experiment". Production activation remains prohibited.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any


FEATURE_FLAG = (
    "SPORTYBET_SUPPLEMENTAL_STAGING_ENABLED"
)


def _truthy(
    value: Any,
) -> bool:
    return (
        str(
            value
            or ""
        )
        .strip()
        .casefold()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def _number(
    value,
) -> float | None:
    try:
        return float(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def candidate_gate(
    pick: dict,
) -> dict:
    """Apply existing production-quality facts; add no new numeric threshold."""
    reasons = []

    if not bool(
        pick.get(
            "bookable"
        )
    ):
        reasons.append(
            "NOT_EXACTLY_BOOKABLE"
        )

    if not bool(
        pick.get(
            "odds_are_real"
        )
    ):
        reasons.append(
            "REAL_PRICE_REQUIRED"
        )

    if not bool(
        pick.get(
            "market_floor_eligible",
            False,
        )
    ):
        reasons.append(
            "BELOW_MARKET_PUBLICATION_FLOOR"
        )

    if not bool(
        pick.get(
            "safe_tier_eligible",
            False,
        )
    ):
        reasons.append(
            "SAFE_TIER_EVIDENCE_NOT_READY"
        )

    if (
        str(
            pick.get(
                "market_trust_state"
            )
            or ""
        )
        != "TRUSTED"
    ):
        reasons.append(
            "MARKET_NOT_TRUSTED"
        )

    probability = _number(
        pick.get(
            "selection_probability"
        )
    )

    if (
        probability is None
        or not 0 < probability < 1
    ):
        reasons.append(
            "SELECTION_PROBABILITY_UNAVAILABLE"
        )

    return {
        "eligible": not reasons,
        "reason_codes": reasons,
    }


def _metric_delta(
    left: dict,
    right: dict,
    key: str,
) -> float | None:
    left_value = _number(
        left.get(key)
    )

    right_value = _number(
        right.get(key)
    )

    if (
        left_value is None
        or right_value is None
    ):
        return None

    return round(
        left_value
        - right_value,
        4,
    )


def evaluate_staging_gate(
    picks: list[dict],
    *,
    board_complete: bool,
    live_summary: dict | None = None,
    shadow_summary: dict | None = None,
    environment: str | None = None,
    feature_flag: bool | None = None,
) -> dict:
    environment = str(
        environment
        if environment is not None
        else os.getenv(
            "ENVIRONMENT",
            "",
        )
    ).strip().casefold()

    if feature_flag is None:
        feature_flag = _truthy(
            os.getenv(
                FEATURE_FLAG,
                "",
            )
        )

    eligible = []

    rejected = []

    reasons = Counter()

    leagues = Counter()

    markets = Counter()

    for pick in picks:
        result = candidate_gate(
            pick
        )

        fixture = (
            pick.get(
                "_fixture"
            )
            or {}
        )

        compact = {
            "match_id": pick.get(
                "match_id"
            ),
            "league": fixture.get(
                "league"
            ),
            "league_slug": fixture.get(
                "league_slug"
            ),
            "market": pick.get(
                "market"
            ),
            "selection_probability": (
                pick.get(
                    "selection_probability"
                )
            ),
            "lower_reliability_bound": (
                pick.get(
                    "lower_reliability_bound"
                )
            ),
            "quality_score": pick.get(
                "quality_score"
            ),
            "market_trust_state": (
                pick.get(
                    "market_trust_state"
                )
            ),
            "market_floor_eligible": bool(
                pick.get(
                    "market_floor_eligible"
                )
            ),
            "safe_tier_eligible": bool(
                pick.get(
                    "safe_tier_eligible"
                )
            ),
            "odds": pick.get(
                "odds"
            ),
            "odds_are_real": bool(
                pick.get(
                    "odds_are_real"
                )
            ),
            "bookable": bool(
                pick.get(
                    "bookable"
                )
            ),
            "reason_codes": list(
                result[
                    "reason_codes"
                ]
            ),
        }

        if result["eligible"]:
            eligible.append(
                compact
            )

            leagues[
                str(
                    compact.get(
                        "league"
                    )
                    or "unknown"
                )
            ] += 1

            markets[
                str(
                    compact.get(
                        "market"
                    )
                    or "unknown"
                )
            ] += 1

        else:
            rejected.append(
                compact
            )

            for reason in result[
                "reason_codes"
            ]:
                reasons[
                    reason
                ] += 1

    structural_ready = bool(
        board_complete
        and eligible
    )

    staging_environment = (
        environment
        == "staging"
    )

    staging_review_enabled = bool(
        structural_ready
        and staging_environment
        and feature_flag
    )

    live_summary = (
        live_summary
        or {}
    )

    shadow_summary = (
        shadow_summary
        or {}
    )

    live_probability = (
        live_summary.get(
            "selection_probability"
        )
        or {}
    )

    shadow_probability = (
        shadow_summary.get(
            "selection_probability"
        )
        or {}
    )

    live_quality = (
        live_summary.get(
            "quality_score"
        )
        or {}
    )

    shadow_quality = (
        shadow_summary.get(
            "quality_score"
        )
        or {}
    )

    return {
        "status": (
            "ready_for_staging_review"
            if staging_review_enabled
            else (
                "structurally_ready_flag_off"
                if structural_ready
                else "blocked"
            )
        ),
        "shadow_only": True,
        "read_only": True,
        "environment": environment,
        "feature_flag": FEATURE_FLAG,
        "feature_flag_enabled": bool(
            feature_flag
        ),
        "board_complete": bool(
            board_complete
        ),
        "candidate_count": len(
            picks
        ),
        "structurally_eligible_count": len(
            eligible
        ),
        "rejected_count": len(
            rejected
        ),
        "rejection_reason_counts": dict(
            reasons
        ),
        "eligible_league_counts": dict(
            leagues
        ),
        "eligible_market_counts": dict(
            markets
        ),
        "staging_review_enabled": (
            staging_review_enabled
        ),
        # There is deliberately no merge implementation in this batch.
        "merge_executed": False,
        "prediction_pool_changed": False,
        "publishing_changed": False,
        "booking_exposed": False,
        "official_record_changed": False,
        "production_merge_allowed": False,
        "eligible_candidates": eligible[
            :30
        ],
        "rejected_samples": rejected[
            :20
        ],
        # Descriptive only. These values are NOT pass/fail thresholds.
        "comparison_to_live": {
            "selection_probability_mean_delta": (
                _metric_delta(
                    shadow_probability,
                    live_probability,
                    "mean",
                )
            ),
            "selection_probability_median_delta": (
                _metric_delta(
                    shadow_probability,
                    live_probability,
                    "median",
                )
            ),
            "quality_score_mean_delta": (
                _metric_delta(
                    shadow_quality,
                    live_quality,
                    "mean",
                )
            ),
            "quality_score_median_delta": (
                _metric_delta(
                    shadow_quality,
                    live_quality,
                    "median",
                )
            ),
            "bookable_rate_delta": (
                _metric_delta(
                    shadow_summary,
                    live_summary,
                    "bookable_rate",
                )
            ),
            "used_as_gate": False,
        },
        "next_gate": (
            "inspect this report on staging before implementing any "
            "feature-flagged supplemental merge"
        ),
    }
