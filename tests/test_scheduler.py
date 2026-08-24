"""
Idempotency and failure isolation for the daily run.

Two properties are worth protecting here.

Running twice must be harmless. The job posts to Telegram and locks the day's
card, and it is triggered from two places — a scheduled workflow and an
in-process loop — precisely so that one failing does not stop publication.
That only works if the second caller reliably does nothing.

One broken step must not lose the rest of the day. A scores provider being
down should not stop the card publishing, and a Telegram outage should not
stop either.
"""

import json

import pytest
from sqlalchemy import text

from database import engine
from leagues import scheduler as S


@pytest.fixture
def run_date():
    """A date no real run will ever claim, cleaned up either side."""
    d = "1999-01-01"

    def _clear():
        with engine.begin() as conn:
            S._ensure_table(conn)
            conn.execute(text("DELETE FROM daily_runs WHERE run_date = :d"),
                         {"d": d})

    _clear()
    yield d
    _clear()


# ── Claiming ───────────────────────────────────────────────

def test_first_claim_succeeds(run_date):
    claimed, why = S._claim(run_date, force=False)
    assert claimed and why == ""


def test_second_claim_is_refused_while_running(run_date):
    S._claim(run_date, force=False)
    claimed, why = S._claim(run_date, force=False)
    assert not claimed
    assert "already running" in why


def test_claim_refused_once_complete(run_date):
    S._claim(run_date, force=False)
    S._finish(run_date, {"status": "complete", "steps": {}, "failed": []})
    claimed, why = S._claim(run_date, force=False)
    assert not claimed
    assert "already completed" in why


def test_force_overrides_a_completed_day(run_date):
    S._claim(run_date, force=False)
    S._finish(run_date, {"status": "complete", "steps": {}, "failed": []})
    claimed, _ = S._claim(run_date, force=True)
    assert claimed


def test_a_stale_claim_can_be_taken_over(run_date):
    """A process killed mid-run must not block the day forever."""
    S._claim(run_date, force=False)
    stale = "1999-01-01T00:00:00+00:00"
    with engine.begin() as conn:
        conn.execute(text("UPDATE daily_runs SET started_at = :t WHERE run_date = :d"),
                     {"d": run_date, "t": stale})
    claimed, _ = S._claim(run_date, force=False)
    assert claimed


def test_an_unparseable_claim_time_does_not_wedge_the_day(run_date):
    S._claim(run_date, force=False)
    with engine.begin() as conn:
        conn.execute(text("UPDATE daily_runs SET started_at = :t WHERE run_date = :d"),
                     {"d": run_date, "t": "not-a-timestamp"})
    claimed, _ = S._claim(run_date, force=False)
    assert claimed


# ── Step isolation ─────────────────────────────────────────

def _report():
    return {"steps": {}, "failed": []}


def test_step_records_success():
    rep = _report()
    assert S._step(rep, "ok", lambda: {"n": 3}) == {"n": 3}
    assert rep["steps"]["ok"]["ok"] is True
    assert rep["failed"] == []


def test_step_swallows_failure_and_records_it():
    rep = _report()

    def _boom():
        raise RuntimeError("provider down")

    assert S._step(rep, "settle", _boom) is None
    assert rep["steps"]["settle"]["ok"] is False
    assert "provider down" in rep["steps"]["settle"]["error"]
    assert rep["failed"] == ["settle"]


def test_one_failure_does_not_stop_later_steps():
    """The point of the isolation: a dead scores feed still lets the card out."""
    rep = _report()
    S._step(rep, "settle", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    S._step(rep, "card", lambda: {"tiers": 6})
    assert rep["failed"] == ["settle"]
    assert rep["steps"]["card"]["ok"] is True


# ── Bookkeeping ────────────────────────────────────────────

def test_history_reports_what_happened(run_date):
    S._claim(run_date, force=False)
    S._finish(run_date, {
        "status": "partial",
        "steps": {"settle": {"ok": False}, "card": {"ok": True}},
        "failed": ["settle"],
    })
    row = next(r for r in S.last_runs(50) if r["run_date"] == run_date)
    assert row["status"] == "partial"
    assert row["failed"] == ["settle"]
    assert row["steps"] == {"settle": False, "card": True}


def test_history_survives_a_corrupt_report(run_date):
    S._claim(run_date, force=False)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE daily_runs SET status = 'complete', report = :r"
                 " WHERE run_date = :d"),
            {"d": run_date, "r": "{not json"})
    row = next(r for r in S.last_runs(50) if r["run_date"] == run_date)
    assert row["status"] == "complete"
    assert row["failed"] == []


def test_finish_truncates_an_oversized_report(run_date):
    S._claim(run_date, force=False)
    S._finish(run_date, {"status": "complete", "steps": {}, "failed": [],
                         "junk": "x" * 50000})
    with engine.begin() as conn:
        stored = conn.execute(
            text("SELECT report FROM daily_runs WHERE run_date = :d"),
            {"d": run_date}).fetchone()[0]
    assert len(stored) <= 8000


def test_run_daily_job_skips_a_completed_day(monkeypatch, run_date):
    """The contract the two triggers depend on: the loser does nothing."""
    monkeypatch.setattr("leagues.daily_feed._publish_date", lambda: run_date)
    S._claim(run_date, force=False)
    S._finish(run_date, {"status": "complete", "steps": {}, "failed": []})

    called = []
    monkeypatch.setattr(S, "_step",
                        lambda rep, name, fn: called.append(name))

    result = S.run_daily_job(publish=True)
    assert result["status"] == "skipped"
    assert called == []
