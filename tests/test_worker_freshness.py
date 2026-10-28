from datetime import datetime, timedelta, timezone

from utils.worker_freshness import evaluate_worker_freshness

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)


def _row(role, ownership, *, age=10, state="running"):
    return {
        "role": role,
        "state": state,
        "heartbeat_at": NOW - timedelta(seconds=age),
        "ownership_json": ownership,
    }


def _healthy_rows():
    return [
        _row("publication", {"scheduler": True, "settlement": False, "telegram": False}),
        _row("settlement", {"scheduler": False, "settlement": True, "telegram": False}),
    ]


def test_normal_split_workers_are_healthy():
    report = evaluate_worker_freshness(_healthy_rows(), now=NOW)
    assert report["healthy"] is True
    assert report["problems"] == []


def test_missing_stale_or_stopped_worker_fails_closed():
    for row in [
        _row("settlement", {"settlement": True}, age=999),
        _row("settlement", {"settlement": True}, state="stopped"),
        _row("settlement", {}, age=10),
    ]:
        report = evaluate_worker_freshness([_healthy_rows()[0], row], now=NOW)
        assert report["healthy"] is False


def test_legacy_render_worker_overlap_is_detected():
    rows = _healthy_rows() + [
        _row("all", {"scheduler": True, "settlement": True, "telegram": True})
    ]
    report = evaluate_worker_freshness(rows, now=NOW)
    assert "duplicate_owner:scheduler" in report["problems"]
    assert "duplicate_owner:settlement" in report["problems"]
    assert "unexpected_owner:telegram" in report["problems"]


def test_telegram_is_optional_only_when_unowned():
    rows = _healthy_rows() + [_row("telegram", {"telegram": True})]
    assert not evaluate_worker_freshness(rows, now=NOW)["healthy"]
    assert evaluate_worker_freshness(
        rows, now=NOW, require_telegram=True
    )["healthy"]
    assert not evaluate_worker_freshness(
        _healthy_rows(), now=NOW, require_telegram=True
    )["healthy"]


def test_invalid_and_future_heartbeats_fail():
    rows = _healthy_rows()
    rows[1] = dict(rows[1], heartbeat_at="broken")
    assert not evaluate_worker_freshness(rows, now=NOW)["healthy"]
    rows[1] = dict(rows[1], heartbeat_at=NOW + timedelta(minutes=10))
    assert not evaluate_worker_freshness(rows, now=NOW)["healthy"]


def test_iso_timestamp_and_duplicate_same_role():
    rows = _healthy_rows()
    rows[0]["heartbeat_at"] = "2026-10-28T08:59:50Z"
    assert evaluate_worker_freshness(rows, now=NOW)["healthy"]
    assert not evaluate_worker_freshness(rows + [rows[0]], now=NOW)["healthy"]
