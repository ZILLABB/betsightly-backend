"""
The daily run.

Everything that has to happen once a day, in order, exactly once. Until this
existed the card was built by whoever happened to request it first — so
publication time was a function of traffic, and on a quiet morning the 08:00
card locked whenever the first visitor turned up. The Telegram post went out
only when something triggered it.

Ordering is deliberate:

  1. settle    yesterday's results, then refit calibration
  2. publish   build and lock today's card
  3. distribute  growth content and Telegram

Settlement comes first because the calibration fit is what the card's
confidences are corrected against, and a fit that is a day stale is a day of
evidence thrown away. Distribution comes last because it reads the card.

Idempotency is claim-before-work, the same shape as the Telegram duplicate
guard: a row keyed on the publishing day is inserted *before* any step runs,
and a second run that finds a completed row returns without doing anything.
The claim lives in the database rather than in memory or on disk, because
Render restarts on every deploy and the filesystem does not survive it — that
is the bug that once burned a month of odds credits in an afternoon.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# How long a claimed-but-unfinished run is trusted before another attempt may
# take it over. Long enough that a slow pipeline is never cut off, short enough
# that a process killed mid-run does not block the day.
STALE_CLAIM_HOURS = 1.5


def _ensure_table(conn) -> None:
    from sqlalchemy import text
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS daily_runs ("
        "  run_date VARCHAR(10) PRIMARY KEY,"
        "  status VARCHAR(16) NOT NULL,"
        "  started_at VARCHAR(32),"
        "  finished_at VARCHAR(32),"
        "  report TEXT)"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim(run_date: str, force: bool) -> tuple[bool, str]:
    """Take the day's run. Returns (claimed, why_not).

    The insert is the lock. Two workers racing both attempt it, one wins on the
    primary key, and the loser is told the day is already taken — which is the
    property that makes running this twice harmless.
    """
    from sqlalchemy import text
    from database import engine
    with engine.begin() as conn:
        _ensure_table(conn)
        row = conn.execute(
            text("SELECT status, started_at FROM daily_runs WHERE run_date = :d"),
            {"d": run_date}).fetchone()

        if row is not None:
            status, started = row[0], row[1]
            if status == "complete" and not force:
                return False, "already completed today"
            if status == "running" and not force:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(started)
                    if age < timedelta(hours=STALE_CLAIM_HOURS):
                        return False, f"already running (started {started})"
                except (TypeError, ValueError):
                    pass
            conn.execute(
                text("UPDATE daily_runs SET status = 'running', started_at = :t,"
                     " finished_at = NULL WHERE run_date = :d"),
                {"d": run_date, "t": _now()})
            return True, ""

        try:
            conn.execute(
                text("INSERT INTO daily_runs (run_date, status, started_at)"
                     " VALUES (:d, 'running', :t)"),
                {"d": run_date, "t": _now()})
        except Exception:
            # Lost the race. The other worker owns the day.
            return False, "claimed by another worker"
        return True, ""


def _finish(run_date: str, report: dict) -> None:
    import json
    from sqlalchemy import text
    from database import engine
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            conn.execute(
                text("UPDATE daily_runs SET status = :s, finished_at = :t,"
                     " report = :r WHERE run_date = :d"),
                {"d": run_date, "s": report.get("status", "complete"),
                 "t": _now(), "r": json.dumps(report)[:8000]})
    except Exception as e:
        logger.warning(f"daily run bookkeeping failed: {e}")


def _persist_progress(run_date: str, report: dict) -> None:
    """Durably expose the active step without marking the run finished."""
    import json
    from sqlalchemy import text
    from database import engine
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            conn.execute(text(
                "UPDATE daily_runs SET status = 'running', report = :r WHERE run_date = :d"),
                {"d": run_date, "r": json.dumps(report)[:8000]})
    except Exception as exc:
        logger.warning(f"daily run progress bookkeeping failed: {exc}")


def _step(report: dict, name: str, fn, run_date: str | None = None):
    """Run one step, recording what happened without letting it end the run.

    A failure to settle yesterday must not stop today's card being published,
    and a Telegram outage must not stop either. Each step is recorded and the
    run continues.
    """
    report["steps"][name] = {"status": "running", "started_at": _now()}
    if run_date:
        _persist_progress(run_date, report)
    try:
        result = fn()
        report["steps"][name] = {"status": "complete", "ok": True,
                                 "started_at": report["steps"][name]["started_at"],
                                 "finished_at": _now(), "detail": result}
        if run_date:
            _persist_progress(run_date, report)
        return result
    except Exception as e:
        logger.error(f"daily run step '{name}' failed: {e}", exc_info=True)
        report["steps"][name] = {"status": "failed", "ok": False,
                                 "started_at": report["steps"][name]["started_at"],
                                 "finished_at": _now(), "error": str(e)[:300]}
        report["failed"].append(name)
        if run_date:
            _persist_progress(run_date, report)
        return None


def run_daily_job(force: bool = False, publish: bool = True) -> dict:
    """The whole day, once. Safe to call repeatedly."""
    from leagues.daily_feed import _publish_date

    run_date = _publish_date()
    report: dict = {
        "run_date": run_date, "status": "complete",
        "steps": {}, "failed": [], "started_at": _now(),
    }

    claimed, why = _claim(run_date, force)
    if not claimed:
        logger.info(f"daily run {run_date}: skipped — {why}")
        return {**report, "status": "skipped", "reason": why}

    logger.info(f"daily run {run_date}: starting")

    # 1. Settle what finished, then refit on the new evidence.
    def _settle():
        from leagues.results_checker import check_all_pending, settle_published_slips
        summary = check_all_pending()
        slips = settle_published_slips()
        return {"scores": summary, "slips": slips}

    _step(report, "settle", _settle, run_date)

    def _recalibrate():
        from leagues.calibrator import fit_calibration
        fit = fit_calibration(force=True)
        return {"legs": fit.get("n", 0)}

    _step(report, "calibrate", _recalibrate, run_date)

    # 2. Build and lock the card. First write wins, so calling this again
    #    later in the day returns the same card rather than replacing it.
    def _publish_card():
        from leagues.daily_feed import build_daily_accumulators
        card = build_daily_accumulators()
        if not card:
            raise RuntimeError("no card produced")
        accs = card.get("accumulators") or {}
        return {
            "date": card.get("date"),
            "revision": card.get("revision"),
            "first_published_at": card.get("first_published_at"),
            "tiers": {k: len(v.get("games") or []) for k, v in accs.items()},
        }

    _step(report, "card", _publish_card, run_date)

    # 3. Book the tiers. After the lock, so a code always describes the card
    #    that was actually published, and before distribution, so the Telegram
    #    post can carry the codes rather than a list to retype.
    def _book():
        from leagues import daily_feed
        from leagues.booking import book_card
        card = daily_feed.build_daily_accumulators()
        report = book_card(run_date, (card or {}).get("accumulators") or {})
        # Drop the served card so the codes appear now rather than whenever
        # the cache next lapses. The card is cached for fifteen minutes and
        # was built by the step above — before any of these codes existed —
        # so without this the site shows a card with no codes on it while the
        # codes sit in the database, and self-heals only on expiry.
        daily_feed._accum_cache.update({"result": None, "ts": 0})
        return report

    _step(report, "book", _book, run_date)

    # 4. Tell subscribers, counted off the card that was actually published.
    #
    # This used to run from application startup, which is why deploying sent
    # a notification: the guard was a dict in process memory, so every new
    # process announced the day again. Here it sits inside the claimed daily
    # run and behind a delivery row of its own, so it fires once per
    # publishing day whatever restarts happen — and it can no longer fire at
    # three in the afternoon announcing the morning's card.
    def _alert():
        from leagues.daily_feed import build_daily_accumulators
        from services.push_notification_service import notify_predictions_ready
        card = build_daily_accumulators()
        accs = (card or {}).get("accumulators") or {}
        cats = {k: bool((c or {}).get("games"))
                for k, c in accs.items() if k != "rollover"}
        count = sum(len((c or {}).get("games") or [])
                    for k, c in accs.items() if k != "rollover")
        if not count:
            return {"sent": False, "reason": "nothing published to announce"}
        notify_predictions_ready(prediction_date=run_date,
                                 predictions_count=count, categories=cats)
        return {"sent": True, "picks": count}

    _step(report, "alert", _alert, run_date)

    # 5. Distribution. Its own duplicate guard sits on
    #    (publish_date, channel, template), so this is safe on a retry too.
    if publish:
        def _distribute():
            from growth.engine import run_daily
            return run_daily(publish=True)

        _step(report, "distribute", _distribute, run_date)
    else:
        report["steps"]["distribute"] = {"ok": True, "detail": "skipped"}

    report["finished_at"] = _now()
    if report["failed"]:
        report["status"] = "partial"
    _finish(run_date, report)
    logger.info(
        f"daily run {run_date}: {report['status']} "
        f"(failed: {report['failed'] or 'none'})")
    return report


def last_runs(limit: int = 14) -> list[dict]:
    """Recent runs, newest first — for the admin dashboard and health checks."""
    import json
    from sqlalchemy import text
    from database import engine
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            rows = conn.execute(text(
                "SELECT run_date, status, started_at, finished_at, report"
                " FROM daily_runs ORDER BY run_date DESC LIMIT :n"),
                {"n": limit}).fetchall()
    except Exception as e:
        logger.warning(f"daily run history unavailable: {e}")
        return []

    out = []
    for r in rows:
        try:
            rep = json.loads(r[4]) if r[4] else {}
        except (TypeError, ValueError):
            rep = {}
        out.append({
            "run_date": r[0], "status": r[1],
            "started_at": r[2], "finished_at": r[3],
            "failed": rep.get("failed") or [],
            "steps": {k: v.get("ok") for k, v in (rep.get("steps") or {}).items()},
        })
    return out
