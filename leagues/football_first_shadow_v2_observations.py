"""Prospective evidence wrapper for the frozen V2 shadow candidate.

V1 and V2 share the immutable observation table, but observation keys include
model_version, so each model owns an independent prospective evidence history.
"""

from __future__ import annotations

import math
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import engine
from leagues import (
    football_first_shadow_observations
    as shared,
)
from leagues import (
    football_first_shadow_v2
    as shadow_v2,
)

PRODUCTION_OVERRIDE_FLAG = (
    "FOOTBALL_FIRST_SHADOW_V2_PRODUCTION_ENABLED"
)
MIN_PROSPECTIVE_REVIEW = 300


def _truthy(
    name: str,
) -> bool:
    return str(
        os.getenv(
            name,
            "false",
        )
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def collection_allowed() -> tuple[bool, str]:

    if not shadow_v2.enabled():
        return (
            False,
            "feature_flag_disabled",
        )

    environment = str(
        os.getenv(
            "ENVIRONMENT",
            "",
        )
    ).strip().lower()

    if (
        environment == "production"
        and not _truthy(
            PRODUCTION_OVERRIDE_FLAG
        )
    ):
        return (
            False,
            "production_override_disabled",
        )

    return (
        True,
        "enabled",
    )


def _persist(
    row: dict,
    *,
    db_engine=engine,
) -> dict:

    shared.ensure_table(
        db_engine
    )

    try:
        with db_engine.begin() as conn:

            existing = conn.execute(
                select(
                    shared.observations.c.observation_id
                ).where(
                    shared.observations.c.observation_key
                    == row[
                        "observation_key"
                    ]
                )
            ).first()

            if existing:
                return {
                    "status":
                        "EXISTS",

                    "reason":
                        "first_write_preserved",

                    "model_version":
                        row[
                            "model_version"
                        ],

                    "fixture_id":
                        row[
                            "fixture_id"
                        ],

                    "shadow_only":
                        True,
                }

            conn.execute(
                shared.observations
                .insert()
                .values(
                    **row
                )
            )

    except IntegrityError:
        return {
            "status":
                "EXISTS",

            "reason":
                "first_write_preserved",

            "model_version":
                row[
                    "model_version"
                ],

            "fixture_id":
                row[
                    "fixture_id"
                ],

            "shadow_only":
                True,
        }

    return {
        "status":
            "RECORDED",

        "model_version":
            row[
                "model_version"
            ],

        "fixture_id":
            row[
                "fixture_id"
            ],

        "league_slug":
            row[
                "league_slug"
            ],

        "observed_at":
            row[
                "observed_at"
            ].isoformat(),

        "kickoff":
            row[
                "kickoff"
            ].isoformat(),

        "shadow_only":
            True,
    }


def observe_fixture(
    fixture: dict,
    champion_model: dict,
    history,
    *,
    cached_rates: dict,
    ratings: dict,
    observed_at: datetime | None = None,
    db_engine=engine,
) -> dict:

    allowed, reason = (
        collection_allowed()
    )

    if not allowed:
        return {
            "status":
                "DISABLED",

            "reason":
                reason,

            "shadow_only":
                True,
        }

    challenger = (
        shadow_v2.predict_fixture(
            fixture,
            history,
            cached_rates,
            ratings,
        )
    )

    row, reason = (
        shared.build_observation(
            fixture,
            champion_model,
            challenger,
            observed_at=(
                observed_at
                or datetime.now(
                    timezone.utc
                )
            ),
        )
    )

    if row is None:
        return {
            "status":
                "SKIPPED",

            "reason":
                reason,

            "challenger_status":
                challenger.get(
                    "status"
                ),

            "shadow_only":
                True,
        }

    return _persist(
        row,
        db_engine=db_engine,
    )


def shadow_report(
    *,
    db_engine=engine,
) -> dict:

    model = (
        shadow_v2.status()
    )

    allowed, gate = (
        collection_allowed()
    )

    current_version = (
        model.get(
            "model_version"
        )
    )

    if (
        not current_version
        or not shared.table_exists(
            db_engine
        )
    ):
        return {
            "status":
                "success",

            "collection_enabled":
                allowed,

            "collection_gate":
                gate,

            "model":
                model,

            "observations": {
                "total":
                    0,
                "pending":
                    0,
                "settled":
                    0,
            },

            "comparison": {
                "n":
                    0,
                "status":
                    "NO_PROSPECTIVE_EVIDENCE",
            },

            "automatic_promotion":
                False,

            "live_adjustment_allowed":
                False,
        }

    with db_engine.begin() as conn:

        rows = [
            dict(
                row
            )
            for row
            in conn.execute(
                select(
                    shared.observations
                )
                .where(
                    shared.observations.c.model_version
                    == current_version
                )
                .order_by(
                    shared.observations.c.observed_at.asc()
                )
            ).mappings().all()
        ]

    settled = [
        row
        for row
        in rows
        if (
            row.get(
                "status"
            )
            == "settled"
            and row.get(
                "outcome_class"
            )
            in {
                0,
                1,
                2,
            }
        )
    ]

    pending = (
        len(
            rows
        )
        - len(
            settled
        )
    )

    champion = (
        shared._metrics(
            settled,
            "champion",
        )
    )

    challenger = (
        shared._metrics(
            settled,
            "challenger",
        )
    )

    gains = [
        shared._paired_brier_gain(
            row
        )
        for row
        in settled
    ]

    if gains:
        n = len(
            gains
        )

        mean = sum(
            gains
        ) / n

        variance = sum(
            (
                value
                - mean
            )
            ** 2
            for value
            in gains
        ) / max(
            1,
            n - 1,
        )

        lower_95 = (
            mean
            - 1.96
            * math.sqrt(
                variance
                / n
            )
        )
    else:
        mean = 0.0
        lower_95 = 0.0

    eligible = bool(
        len(
            settled
        )
        >= MIN_PROSPECTIVE_REVIEW
        and lower_95 > 0
        and challenger.get(
            "log_loss",
            float(
                "inf"
            ),
        )
        <= champion.get(
            "log_loss",
            float(
                "inf"
            ),
        )
        and challenger.get(
            "top_label_ece",
            float(
                "inf"
            ),
        )
        <= champion.get(
            "top_label_ece",
            float(
                "inf"
            ),
        )
    )

    by_league = {}

    for slug in sorted({
        row[
            "league_slug"
        ]
        for row
        in settled
    }):

        subset = [
            row
            for row
            in settled
            if row[
                "league_slug"
            ]
            == slug
        ]

        if (
            len(
                subset
            )
            < 30
        ):
            continue

        by_league[
            slug
        ] = {
            "n":
                len(
                    subset
                ),

            "champion":
                shared._metrics(
                    subset,
                    "champion",
                ),

            "challenger":
                shared._metrics(
                    subset,
                    "challenger",
                ),
        }

    started_at = (
        rows[
            0
        ][
            "observed_at"
        ].isoformat()
        if rows
        else None
    )

    return {
        "status":
            "success",

        "collection_enabled":
            allowed,

        "collection_gate":
            gate,

        "model":
            model,

        "observations": {
            "total":
                len(
                    rows
                ),

            "pending":
                pending,

            "settled":
                len(
                    settled
                ),

            "prospective_started_at":
                started_at,
        },

        "comparison": {
            "n":
                len(
                    settled
                ),

            "minimum_for_human_review":
                MIN_PROSPECTIVE_REVIEW,

            "champion":
                champion,

            "challenger":
                challenger,

            "paired_brier_improvement":
                round(
                    mean,
                    6,
                ),

            "lower_95pct_brier_improvement":
                round(
                    lower_95,
                    6,
                ),

            "status":
                (
                    "ELIGIBLE_FOR_HUMAN_REVIEW"
                    if eligible
                    else (
                        "COLLECTING_PROSPECTIVE_EVIDENCE"
                        if settled
                        else "NO_PROSPECTIVE_EVIDENCE"
                    )
                ),

            "by_league":
                by_league,
        },

        "historical_replay_counts_toward_threshold":
            False,

        "v1_evidence_counts_toward_v2_threshold":
            False,

        "evidence_progress": {
            "minimum_for_human_review":
                MIN_PROSPECTIVE_REVIEW,

            "settled":
                len(
                    settled
                ),

            "remaining":
                max(
                    0,
                    MIN_PROSPECTIVE_REVIEW
                    - len(
                        settled
                    ),
                ),

            "percent_complete":
                round(
                    min(
                        100.0,
                        100.0
                        * len(
                            settled
                        )
                        / MIN_PROSPECTIVE_REVIEW,
                    ),
                    2,
                ),
        },

        "automatic_promotion":
            False,

        "live_adjustment_allowed":
            False,
    }


def _current_model_version() -> str:
    return str(
        (
            shadow_v2.status()
            or {}
        ).get(
            "model_version"
        )
        or ""
    ).strip()


def latest_review(
    *,
    db_engine=engine,
) -> dict | None:
    """Return only the latest review for the frozen V2 candidate."""

    model_version = (
        _current_model_version()
    )

    if not model_version:
        return None

    return shared.latest_review(
        model_version=model_version,
        db_engine=db_engine,
    )


def review_packet(
    *,
    db_engine=engine,
) -> dict:
    """Human-review packet for V2 only.

    Historical replay and V1 prospective evidence never count toward
    the V2 promotion threshold.
    """

    report = shadow_report(
        db_engine=db_engine
    )

    comparison = (
        report.get(
            "comparison"
        )
        or {}
    )

    model = (
        report.get(
            "model"
        )
        or {}
    )

    current_settled = int(
        comparison.get(
            "n"
        )
        or 0
    )

    eligible = (
        comparison.get(
            "status"
        )
        == "ELIGIBLE_FOR_HUMAN_REVIEW"
    )

    return {
        "status":
            "success",

        "model":
            model,

        "evidence": {
            "observations":
                report.get(
                    "observations"
                ),

            "comparison":
                comparison,

            "eligible_league_ids":
                model.get(
                    "eligible_league_ids"
                )
                or [],

            "historical_replay_counts_toward_threshold":
                False,

            "v1_evidence_counts_toward_v2_threshold":
                False,
        },

        "review_gate": {
            "eligible":
                eligible,

            "minimum_settled":
                MIN_PROSPECTIVE_REVIEW,

            "current_settled":
                current_settled,

            "remaining_to_minimum":
                max(
                    0,
                    MIN_PROSPECTIVE_REVIEW
                    - current_settled,
                ),

            "required_conditions": [
                "V2 settled prospective fixtures >= 300",
                "paired Brier lower 95% confidence bound > 0",
                "V2 log loss <= champion log loss",
                "V2 calibration error <= champion calibration error",
            ],
        },

        "allowed_decisions":
            sorted(
                shared.REVIEW_DECISIONS
            ),

        "latest_review":
            latest_review(
                db_engine=db_engine
            ),

        "promotion_effective":
            False,

        "automatic_promotion":
            False,

        "live_adjustment_allowed":
            False,
    }


def record_review(
    decision: str,
    *,
    reviewer: str | None = None,
    note: str | None = None,
    db_engine=engine,
) -> dict:
    """Record a human V2 decision without switching the live model."""

    normalized = str(
        decision
        or ""
    ).strip().upper()

    if (
        normalized
        not in shared.REVIEW_DECISIONS
    ):
        raise ValueError(
            "invalid_review_decision"
        )

    packet = review_packet(
        db_engine=db_engine
    )

    gate = packet[
        "review_gate"
    ]

    comparison = (
        packet[
            "evidence"
        ].get(
            "comparison"
        )
        or {}
    )

    model = (
        packet.get(
            "model"
        )
        or {}
    )

    if (
        normalized
        == "APPROVE_FOR_PROMOTION_IMPLEMENTATION"
        and not gate[
            "eligible"
        ]
    ):
        raise ValueError(
            "promotion_review_gate_not_met"
        )

    model_version = str(
        model.get(
            "model_version"
        )
        or ""
    ).strip()

    if not model_version:
        raise ValueError(
            "missing_v2_model_version"
        )

    shared.ensure_table(
        db_engine
    )

    row = {
        "review_id":
            str(
                uuid.uuid4()
            ),

        "model_version":
            model_version,

        "evidence_n":
            int(
                comparison.get(
                    "n"
                )
                or 0
            ),

        "evidence_status":
            str(
                comparison.get(
                    "status"
                )
                or "NO_PROSPECTIVE_EVIDENCE"
            ),

        "decision":
            normalized,

        "reviewer":
            (
                str(
                    reviewer
                )[:160]
                if reviewer
                else None
            ),

        "note":
            (
                str(
                    note
                )[:2000]
                if note
                else None
            ),

        "created_at":
            datetime.now(
                timezone.utc
            ),
    }

    with db_engine.begin() as conn:
        conn.execute(
            shared.reviews
            .insert()
            .values(
                **row
            )
        )

    return {
        "status":
            "RECORDED",

        "review":
            row,

        "promotion_effective":
            False,

        "automatic_promotion":
            False,

        "live_adjustment_allowed":
            False,

        "next_action": (
            "separate_code_review_and_deployment_required"
            if normalized
            == "APPROVE_FOR_PROMOTION_IMPLEMENTATION"
            else "keep_current_champion"
        ),
    }


def settle_pending_observations(
    *,
    now: datetime | None = None,
    limit: int = 250,
    db_engine=engine,
) -> dict:
    """Settle only rows belonging to the current V2 model version."""

    model_version = (
        _current_model_version()
    )

    if not model_version:
        return {
            "status":
                "NO_MODEL_VERSION",

            "checked":
                0,

            "settled":
                0,

            "pending":
                0,
        }

    return (
        shared
        .settle_pending_observations(
            now=now,
            limit=limit,
            model_version=model_version,
            db_engine=db_engine,
        )
    )


def start_settlement_async(
    *,
    force: bool = False,
    db_engine=engine,
) -> dict:
    """Start V2-only settlement through the shared singleflight worker."""

    model_version = (
        _current_model_version()
    )

    if not model_version:
        return {
            "status":
                "SKIPPED",

            "reason":
                "missing_v2_model_version",

            "shadow_only":
                True,
        }

    return (
        shared
        .start_settlement_async(
            force=force,
            model_version=model_version,
            db_engine=db_engine,
        )
    )
