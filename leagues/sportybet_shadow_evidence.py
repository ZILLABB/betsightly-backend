"""Staging-only aggregate settled-evidence overlay.

This module exists because the isolated staging database intentionally does
not contain production published-slip history.

It NEVER:
  * copies production rows into staging
  * changes probabilities or calibration shifts
  * lowers MIN_EVIDENCE_LEGS
  * changes market trust
  * changes publication floors
  * publishes or books supplemental fixtures
  * enables production merge

It only allows the supplemental SHADOW gate to ask:

"Would this market satisfy the existing safe-tier evidence requirement if we
used a read-only aggregate count of the real settled production history?"
"""

from __future__ import annotations

import json
import os
from collections import Counter
from copy import deepcopy

from leagues.market_registry import CALIBRATION_GROUP
from leagues.picks import (
    MIN_EVIDENCE_LEGS,
    competition_evidence_allows_safe_tier,
)
from leagues.sportybet_shadow_gate import (
    evaluate_staging_gate,
)


EVIDENCE_SNAPSHOT_ENV = (
    "SPORTYBET_SUPPLEMENTAL_EVIDENCE_SNAPSHOT_JSON"
)


def load_evidence_snapshot(
    raw=None,
) -> dict | None:
    """Parse a non-sensitive aggregate evidence snapshot."""
    if raw is None:
        raw = os.getenv(
            EVIDENCE_SNAPSHOT_ENV,
            "",
        )

    if isinstance(raw, dict):
        payload = raw

    else:
        value = str(
            raw or ""
        ).strip()

        if not value:
            return None

        try:
            payload = json.loads(
                value
            )

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

    if not isinstance(
        payload,
        dict,
    ):
        return None

    groups = payload.get(
        "groups"
    )

    if not isinstance(
        groups,
        dict,
    ):
        return None

    cleaned = {}

    for group, value in groups.items():
        group = str(
            group or ""
        ).strip()

        if not group:
            continue

        try:
            count = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if count < 0:
            continue

        cleaned[group] = count

    if not cleaned:
        return None

    return {
        "version": str(
            payload.get(
                "version"
            )
            or "settled-evidence-snapshot-v1"
        ),
        "captured_at": payload.get(
            "captured_at"
        ),
        "source": str(
            payload.get(
                "source"
            )
            or "aggregate"
        ),
        "groups": cleaned,
    }


def _snapshot_evidence_for_pick(
    pick: dict,
    snapshot: dict,
) -> tuple[str | None, int, bool]:
    market = str(
        pick.get(
            "market"
        )
        or ""
    )

    group = CALIBRATION_GROUP.get(
        market
    )

    if not group:
        return None, 0, False

    sample = int(
        (
            snapshot.get(
                "groups"
            )
            or {}
        ).get(
            group,
            0,
        )
        or 0
    )

    fixture = (
        pick.get(
            "_fixture"
        )
        or {}
    )

    ready = bool(
        sample
        >= MIN_EVIDENCE_LEGS
        and competition_evidence_allows_safe_tier(
            fixture
        )
    )

    return (
        group,
        sample,
        ready,
    )


def _empty_report(
    *,
    status: str,
    environment: str,
    snapshot: dict | None,
) -> dict:
    return {
        "status": status,
        "shadow_only": True,
        "read_only": True,
        "environment": environment,
        "evidence_source": (
            "production_aggregate_snapshot"
        ),
        "snapshot_configured": bool(
            snapshot
        ),
        "snapshot_version": (
            snapshot.get("version")
            if snapshot
            else None
        ),
        "snapshot_captured_at": (
            snapshot.get(
                "captured_at"
            )
            if snapshot
            else None
        ),
        "minimum_evidence_legs": (
            MIN_EVIDENCE_LEGS
        ),
        "structurally_eligible_count": 0,
        "staging_review_enabled": False,
        "merge_executed": False,
        "prediction_pool_changed": False,
        "publishing_changed": False,
        "booking_exposed": False,
        "official_record_changed": False,
        "production_merge_allowed": False,
    }


def evaluate_evidence_snapshot_gate(
    picks: list[dict],
    *,
    board_complete: bool,
    live_summary: dict | None = None,
    shadow_summary: dict | None = None,
    environment: str | None = None,
    feature_flag: bool | None = None,
    snapshot: dict | None = None,
) -> dict:
    """Run the normal staging gate with aggregate evidence counts only."""
    environment = str(
        environment
        if environment is not None
        else os.getenv(
            "ENVIRONMENT",
            "",
        )
    ).strip().casefold()

    snapshot = (
        load_evidence_snapshot(
            snapshot
        )
        if snapshot is not None
        else load_evidence_snapshot()
    )

    if environment != "staging":
        return _empty_report(
            status=(
                "not_applicable_outside_staging"
            ),
            environment=environment,
            snapshot=snapshot,
        )

    if snapshot is None:
        return _empty_report(
            status="not_configured",
            environment=environment,
            snapshot=None,
        )

    adjusted = []

    group_usage = Counter()

    local_safe_count = 0

    snapshot_safe_count = 0

    evidence_index = {}

    for pick in picks:
        clone = deepcopy(
            pick
        )

        local_safe = bool(
            pick.get(
                "safe_tier_eligible"
            )
        )

        if local_safe:
            local_safe_count += 1

        (
            group,
            sample,
            snapshot_safe,
        ) = _snapshot_evidence_for_pick(
            pick,
            snapshot,
        )

        if group:
            group_usage[
                group
            ] += 1

        if snapshot_safe:
            snapshot_safe_count += 1

        clone[
            "safe_tier_eligible"
        ] = snapshot_safe

        key = (
            str(
                clone.get(
                    "match_id"
                )
                or ""
            ),
            str(
                clone.get(
                    "market"
                )
                or ""
            ),
        )

        evidence_index[key] = {
            "calibration_group": group,
            "aggregate_settled_sample": (
                sample
            ),
            "local_safe_tier_eligible": (
                local_safe
            ),
            "snapshot_safe_tier_eligible": (
                snapshot_safe
            ),
        }

        adjusted.append(
            clone
        )

    report = evaluate_staging_gate(
        adjusted,
        board_complete=board_complete,
        live_summary=live_summary,
        shadow_summary=shadow_summary,
        environment=environment,
        feature_flag=feature_flag,
    )

    # Add the aggregate evidence facts to the compact gate samples.
    for collection in (
        "eligible_candidates",
        "rejected_samples",
    ):
        for item in (
            report.get(
                collection
            )
            or []
        ):
            key = (
                str(
                    item.get(
                        "match_id"
                    )
                    or ""
                ),
                str(
                    item.get(
                        "market"
                    )
                    or ""
                ),
            )

            item.update(
                evidence_index.get(
                    key,
                    {},
                )
            )

    mature_groups = {
        group: count
        for group, count
        in (
            snapshot.get(
                "groups"
            )
            or {}
        ).items()
        if int(count)
        >= MIN_EVIDENCE_LEGS
    }

    report.update({
        "evidence_source": (
            "production_aggregate_snapshot"
        ),
        "snapshot_configured": True,
        "snapshot_version": snapshot.get(
            "version"
        ),
        "snapshot_captured_at": (
            snapshot.get(
                "captured_at"
            )
        ),
        "minimum_evidence_legs": (
            MIN_EVIDENCE_LEGS
        ),
        "local_safe_tier_candidate_count": (
            local_safe_count
        ),
        "snapshot_safe_tier_candidate_count": (
            snapshot_safe_count
        ),
        "snapshot_group_counts": dict(
            snapshot.get(
                "groups"
            )
            or {}
        ),
        "snapshot_mature_groups": (
            mature_groups
        ),
        "candidate_group_usage": dict(
            group_usage
        ),
        # Explicitly repeat the protections.
        "merge_executed": False,
        "prediction_pool_changed": False,
        "publishing_changed": False,
        "booking_exposed": False,
        "official_record_changed": False,
        "production_merge_allowed": False,
    })

    return report
