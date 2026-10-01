"""Prospective evidence wrapper for the frozen V2 shadow candidate.

V1 and V2 share the immutable observation table, but observation keys include
model_version, so each model owns an independent prospective evidence history.
"""

from __future__ import annotations

import math
import os
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


# Shared settlement deliberately handles all model_version rows.
settle_pending_observations = (
    shared.settle_pending_observations
)

start_settlement_async = (
    shared.start_settlement_async
)
