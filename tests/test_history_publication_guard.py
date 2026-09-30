from leagues import scheduler


def test_failed_card_never_runs_booking_alert_or_distribution(monkeypatch):
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
