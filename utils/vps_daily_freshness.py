"""Read-only daily publication acceptance check for BetSightly.

The publishing day starts at 08:00 West Africa Time (UTC+1).
This diagnoses run status, not tier selection quality.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

WAT = timezone(timedelta(hours=1))


def check_daily_publication(row, *, now=None, grace_minutes=90):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("time must be timezone-aware")
    wat = current.astimezone(WAT)
    if not 0 <= grace_minutes <= 360:
        raise ValueError("grace must be between 0 and 360 minutes")
    deadline = wat.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(
        minutes=grace_minutes
    )
    expected_day = wat.date().isoformat()
    if wat < deadline:
        return {"healthy": True, "status": "before_publication_deadline",
                "run_date": expected_day, "deadline_wat": deadline.isoformat(),
                "problems": []}
    errors = []
    if row is None:
        errors.append("daily_run_missing")
    else:
        if row.get("run_date") != expected_day:
            errors.append("daily_run_wrong_date")
        if row.get("status") != "complete":
            errors.append("daily_run_not_complete")
        raw = row.get("report")
        try:
            report = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            report = None
        if not isinstance(report, dict):
            errors.append("daily_report_missing_or_invalid")
        else:
            steps = report.get("steps")
            if not isinstance(steps, dict) or not isinstance(steps.get("card"), dict):
                errors.append("daily_card_step_missing")
            elif steps["card"].get("ok") is not True:
                errors.append("daily_card_not_verified")
            if report.get("failed"):
                errors.append("daily_run_failed_steps")
    return {"healthy": not errors, "status": "ok" if not errors else "unhealthy",
            "run_date": expected_day, "deadline_wat": deadline.isoformat(),
            "problems": errors}
