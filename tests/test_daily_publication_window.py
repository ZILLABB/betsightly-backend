from datetime import datetime, timezone

from leagues import daily_feed, scheduler


def test_daily_job_cannot_claim_before_0800_wat(monkeypatch):
    # 06:30 UTC = 07:30 WAT. The normal entry point must not claim/build.
    monkeypatch.setattr(
        daily_feed, "_wat_now",
        lambda now=None: datetime(2026, 10, 5, 7, 30, tzinfo=timezone.utc),
    )
    result = scheduler.start_daily_job(force=False)
    assert result["status"] == "skipped"
    assert result["queued"] is False
    assert "08:00 WAT" in result["reason"]


def test_force_is_explicit_early_publication_override(monkeypatch):
    monkeypatch.setattr(
        daily_feed, "_wat_now",
        lambda now=None: datetime(2026, 10, 5, 7, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(scheduler, "_claim", lambda *_: (False, "test claim"))
    result = scheduler.start_daily_job(force=True)
    assert result["status"] == "skipped"
    assert result["reason"] == "test claim"
