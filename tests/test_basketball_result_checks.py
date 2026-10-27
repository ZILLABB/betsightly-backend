"""Proof that an NBA scheduler result check is observed, not inferred."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from growth import basketball_result_checks as ops
from growth import basketball_scheduler as scheduler


@pytest.fixture
def isolated():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    try:
        yield engine
    finally:
        engine.dispose()


def test_absent_cron_receipt_is_not_observed(isolated):
    assert ops.snapshot(engine=isolated)["state"] == "not_observed"


def test_verified_checks_are_distinct_from_game_results(isolated):
    now = datetime(2026, 10, 27, 17, 10, tzinfo=timezone.utc)
    ops.record({"status":"success","nba_final_legs":0,"tickets_updated":0},
               engine=isolated,now=now)
    report = ops.snapshot(engine=isolated,now=now+timedelta(minutes=12))
    assert report["state"] == "observed"
    assert report["recent_checks"] == 1
    assert report["verified_final_legs"] == 0
    assert report["tickets_updated"] == 0
    ops.record({"status":"success","nba_final_legs":2,"tickets_updated":1},
               engine=isolated,now=now+timedelta(minutes=14))
    report = ops.snapshot(engine=isolated,now=now+timedelta(minutes=20))
    assert report["verified_final_legs"] == 2
    assert report["tickets_updated"] == 1


def test_stale_cron_and_bad_provider_are_not_marked_healthy(isolated):
    start = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)
    ops.record({"status":"unavailable","reason":"SCORE_PROVIDER_PARTIAL"},
               engine=isolated,now=start)
    assert ops.snapshot(engine=isolated,now=start+timedelta(minutes=1))["state"] == "degraded"
    assert ops.snapshot(engine=isolated,now=start+timedelta(minutes=36))["state"] == "stale"


def test_audit_limited_and_bad_recorder_cannot_block_real_settlement(isolated):
    start = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)
    for i in range(ops.MAX_EVENTS+4):
        ops.record({"status":"success","nba_final_legs":0,"tickets_updated":0},
                   engine=isolated,now=start+timedelta(minutes=i))
    snap=ops.snapshot(engine=isolated,now=start+timedelta(minutes=ops.MAX_EVENTS+5))
    assert snap["recent_checks"] == 12
    assert snap["verified_final_legs"] == 0
    called=[]
    result=scheduler.tick(
      settle=lambda:{"status":"success","nba_final_legs":1,"tickets_updated":1},
      recorder=lambda x: called.append(x),
    )
    assert result["status"]=="success"
    assert called[0]["nba_final_legs"] == 1
    assert scheduler.tick(
      settle=lambda:{"status":"success","nba_final_legs":0,"tickets_updated":0},
      recorder=lambda _: (_ for _ in ()).throw(ConnectionError("audit unavailable")),
    )["status"]=="success"


def test_bad_audit_input_fails_closed(isolated):
    with pytest.raises(ValueError):
        ops.record({"status":"success","nba_final_legs":True,"tickets_updated":1},
                   engine=isolated)
