"""Pure heartbeat/ownership evaluator for the *separate* VPS services.

Only process presence is assessed. A live heartbeat never establishes that
predictions, final-score collection or settlements are succeeding.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


CAPABILITY_ROLE = {
    "scheduler": "publication",
    "settlement": "settlement",
    "telegram": "telegram",
}


def _timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ownership(value):
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def evaluate_worker_freshness(
    rows,
    *,
    now=None,
    stale_seconds=120,
    require_telegram=False,
):
    """Fail closed on missing/duplicate/incorrect VPS process owners.

    `rows` are read from runtime_process_heartbeats. Old Render workers
    that still own the same work become a conflicting owner immediately.
    """
    current = _timestamp(now or datetime.now(timezone.utc))
    if current is None:
        raise ValueError("invalid observation time")
    if int(stale_seconds) < 30:
        raise ValueError("stale_seconds must be >= 30")

    expected = {"scheduler", "settlement"}
    if require_telegram:
        expected.add("telegram")

    active = []
    stale = []
    invalid = 0

    for row in rows:
        role = str(row.get("role") or "")
        stamp = _timestamp(row.get("heartbeat_at"))
        if stamp is None:
            invalid += 1
            continue
        age = (current - stamp).total_seconds()
        if (
            str(row.get("state") or "").lower() != "running"
            or age < -30
            or age > int(stale_seconds)
        ):
            stale.append(role)
            continue
        active.append({
            "role": role,
            "ownership": _ownership(row.get("ownership_json", row.get("ownership"))),
            "age_seconds": max(0, int(age)),
        })

    problems = []
    for capability, proper_role in CAPABILITY_ROLE.items():
        owners = [
            row["role"] for row in active
            if row["ownership"].get(capability) is True
        ]
        # Any parallel owner is unsafe, including old 'all' Render workers.
        if len(owners) > 1:
            problems.append(f"duplicate_owner:{capability}")
        if capability in expected:
            if not owners:
                problems.append(f"missing_owner:{capability}")
            elif owners != [proper_role]:
                problems.append(f"wrong_owner:{capability}")
        elif owners:
            problems.append(f"unexpected_owner:{capability}")

    # A process with expected role but no ownership is not a healthy worker.
    for required_role in (CAPABILITY_ROLE[k] for k in expected):
        if not any(row["role"] == required_role for row in active):
            problems.append(f"missing_role:{required_role}")

    return {
        "healthy": not problems,
        "problems": sorted(set(problems)),
        "active_roles": sorted(row["role"] for row in active),
        "stale_roles": sorted(stale),
        "invalid_heartbeats": invalid,
        "max_age_seconds": int(stale_seconds),
    }
