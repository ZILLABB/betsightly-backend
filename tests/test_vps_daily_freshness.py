import json
from datetime import datetime, timezone

import pytest

from utils.vps_daily_freshness import check_daily_publication


def _now(h=9, m=0):
    return datetime(2026, 10, 28, h, m, tzinfo=timezone.utc)


def _row(status="complete", card_ok=True, failed=None):
    return {"run_date": "2026-10-28", "status": status, "report": json.dumps({
        "status": status, "failed": failed or [],
        "steps": {"card": {"ok": card_ok, "status": "complete"}}
    })}


def test_wat_deadline_allows_prepublication_without_false_alarm():
    assert check_daily_publication(None, now=_now(6, 30))["healthy"]
    assert check_daily_publication(None, now=_now(7, 40))["healthy"]


def test_missing_after_deadline_is_detected():
    out = check_daily_publication(None, now=_now(9, 0))
    assert not out["healthy"]
    assert out["problems"] == ["daily_run_missing"]


def test_completed_card_is_accepted():
    assert check_daily_publication(_row(), now=_now(9, 0))["healthy"]


@pytest.mark.parametrize("row,problem", [
    (_row(status="partial"), "daily_run_not_complete"),
    (_row(card_ok=False), "daily_card_not_verified"),
    (_row(failed=["book"]), "daily_run_failed_steps"),
    ({"run_date": "2026-10-28", "status": "complete", "report": "oops"},
     "daily_report_missing_or_invalid"),
    ({"run_date": "2026-10-28", "status": "complete", "report": "{}"},
     "daily_card_step_missing"),
    ({"run_date": "2026-10-27", "status": "complete", "report": "{}"},
     "daily_run_wrong_date"),
])
def test_run_failures_are_visible(row, problem):
    assert problem in check_daily_publication(row, now=_now(9, 0))["problems"]


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        check_daily_publication(_row(), now=_now(), grace_minutes=-5)
