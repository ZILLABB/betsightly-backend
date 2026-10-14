from datetime import datetime
from leagues import scheduler


def test_failed_card_never_runs_booking_alert_or_distribution(monkeypatch):
    # This tests a post-publication failure, not the 08:00 WAT gate.
    monkeypatch.setattr("leagues.daily_feed._wat_now",
                        lambda: datetime.fromisoformat("2026-10-14T09:00:00+01:00"))
    steps = []
    finished = []
    monkeypatch.setattr(scheduler, "_claim", lambda *args: (True, ""))
    monkeypatch.setattr(scheduler, "_persist_progress", lambda *args: None)
    monkeypatch.setattr(scheduler, "_finish",
                        lambda date, report: finished.append(report.copy()))
    monkeypatch.setattr("database.log_pool_status", lambda *args, **kw: {})

    def step(report, name, fn, run_date=None):
        steps.append(name)
        failed = name == "card"
        report["steps"][name] = {"status": "failed" if failed else "complete",
                                 "ok": not failed}
        if failed:
            report["failed"].append(name)

    monkeypatch.setattr(scheduler, "_step", step)
    report = scheduler.run_daily_job()
    assert report["status"] == "partial"
    assert steps == ["settle", "calibrate", "weekly_board", "card"]
    assert finished and finished[0]["failed"] == ["card"]
