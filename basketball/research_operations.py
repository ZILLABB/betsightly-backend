"""Stage 2D: read-only first-forecast and settlement operations monitor.

No network, model unpickling, simulated forecasts, changes to SQLite, or
interaction with production. Reports readiness against immutable paper rows.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from basketball.research_prospective import prospective_report
from basketball.research_readiness import _model_cutoff, build_readiness, _timestamp
from basketball.research_data import read_games

PENDING_GRACE_HOURS = 4
DAILY_CYCLE_MAX_AGE_HOURS = 30


def _ledger_state(path: Path) -> tuple[list[dict], datetime | None]:
    """Read real ledger rows without CREATE TABLE or altering the database."""
    if not path.is_file():
        return [], None
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute("""
            SELECT f.game_id, f.fixture_date, f.start_utc, f.created_at,
                   f.inserted_at, f.home_win_probability, f.sha256,
                   s.recorded_at, s.home_score, s.away_score, s.source
              FROM forecasts f LEFT JOIN settlements s ON f.game_id=s.game_id
             ORDER BY f.start_utc, f.game_id
        """).fetchall()]
        latest = db.execute("""
            SELECT occurred_at FROM research_events
             WHERE kind='cycle' ORDER BY id DESC LIMIT 1
        """).fetchone()
    return rows, (_timestamp(latest["occurred_at"]) if latest else None)


def build_operations(
    games: list[dict], forecasts: list[dict], *,
    now: datetime | None = None,
    model_exists: bool = True,
    model_cutoff: str | None = None,
    last_cycle: datetime | None = None,
    prospective: dict | None = None,
) -> dict:
    """Compare all upcoming fixtures with saved immutable pregame rows.

    A missing forecast is a candidate for investigation, never a fabricated
    losing pick. Past opportunities are not backfilled or counted as trials.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Operations clock must be timezone-aware")
    instant = now.astimezone(timezone.utc)
    if last_cycle is not None and (
        last_cycle.tzinfo is None or last_cycle.utcoffset() is None):
        raise ValueError("Last cycle must be timezone-aware")
    readiness = build_readiness(
        games, now=instant, days_ahead=7, model_exists=model_exists,
        model_cutoff=model_cutoff,
    )
    saved = {str(row["game_id"]): row for row in forecasts}
    ready = [r for r in readiness["fixtures"] if r["eligible"]]
    # The 18:00 local scheduled job forecasts exactly two provider date labels
    # (UTC date of the run and the following UTC date).
    date_start = instant.date()
    eligible_for_cycle = [
        r for r in ready
        if date_start <= datetime.fromisoformat(r["date"]).date()
        <= date_start + timedelta(days=1)
    ]
    unsaved = [r for r in eligible_for_cycle
               if r["game_id"] not in saved]
    recorded = [r for r in eligible_for_cycle
                if r["game_id"] in saved]
    all_pending = [r for r in forecasts if r["recorded_at"] is None]
    overdue = [
        r for r in all_pending
        if (tipoff := _timestamp(r.get("start_utc"))) is not None and
        tipoff + timedelta(hours=PENDING_GRACE_HOURS) < instant
    ]
    last = last_cycle.astimezone(timezone.utc) if last_cycle else None
    cycle_age = ((instant-last).total_seconds()/3600) if last else None
    # Read-only source freshness can be newer than the last scheduled cycle,
    # so don't accuse an older cycle of skipping newly eligible games.
    snapshot_time = _timestamp(readiness["snapshot"].get("last_retrieved_at"))
    cycle_processed_snapshot = bool(
        last and snapshot_time and last >= snapshot_time and last <= instant)
    # Last cycle may be up to ~30h old after a missed Windows scheduled run.
    cycle_status = (
        "not_seen" if last is None else
        "clock_skew" if cycle_age is not None and cycle_age < -5/60 else
        "stale" if cycle_age is not None and
        cycle_age > DAILY_CYCLE_MAX_AGE_HOURS else "recent"
    )
    concerns = []
    if readiness["snapshot"]["status"] != "fresh":
        concerns.append("source_not_fresh")
    if cycle_status in ("stale", "not_seen", "clock_skew"):
        concerns.append("daily_cycle_" + cycle_status)
    if overdue:
        concerns.append("overdue_pending_forecasts")
    if prospective and prospective.get("status") == "integrity_failed":
        concerns.append("ledger_integrity_failed")
    if unsaved and cycle_processed_snapshot and cycle_status == "recent":
        concerns.append("eligible_not_saved_after_cycle")
    verified_final_count = sum(r["recorded_at"] is not None for r in forecasts)
    state = (
        "attention_required" if concerns else
        "first_settlement_verified" if verified_final_count else
        "forecast_pending_settlement" if forecasts else
        "eligible_for_first_forecast" if eligible_for_cycle else
        "warming_up"
    )
    return {
        "status": "research_only",
        "phase": "stage_2d_first_forecast",
        "operational_state": state,
        "generated_at": instant.isoformat(),
        "daily_cycle": {
            "last_seen_at": last.isoformat() if last else None,
            "status": cycle_status,
            "age_hours": round(cycle_age, 2) if cycle_age is not None else None,
            "handled_current_snapshot": cycle_processed_snapshot,
            "expected_window": "UTC provider dates today and tomorrow",
        },
        "source": {
            "status": readiness["snapshot"]["status"],
            "last_retrieved_at": readiness["snapshot"]["last_retrieved_at"],
        },
        "upcoming_next_7_days": readiness["upcoming_fixtures"],
        "teams_feature_ready_next_7_days": sum(
            r["feature_ready"] and r["fixture_state"] == "upcoming"
            for r in readiness["fixtures"]
        ),
        "eligible_next_7_days": len(ready),
        "eligible_in_daily_cycle_window": len(eligible_for_cycle),
        "already_recorded_in_daily_window": len(recorded),
        "eligible_not_yet_recorded": [{
            "game_id": r["game_id"], "date": r["date"],
            "start_utc": r["start_utc"],
            "home_team": r["home_team"], "away_team": r["away_team"],
        } for r in unsaved[:20]],
        "total_recorded_paper_forecasts": len(forecasts),
        "verified_paper_settlements": verified_final_count,
        "pending_paper_forecasts": len(all_pending),
        "overdue_pending": [{
            "game_id": str(r["game_id"]),
            "start_utc": r["start_utc"],
            "hours_since_tipoff": round(
                (instant-_timestamp(r["start_utc"])).total_seconds()/3600, 2),
        } for r in overdue[:20]],
        "warnings": concerns,
        "prospective_integrity": (
            prospective.get("status") if prospective else "not_checked"),
        "next_step": (
            "Inspect daily research task, source freshness and pending scores"
            if concerns else
            "Genuine first paper settlement recorded; review calibration"
            if verified_final_count else
            "Continue hourly verified-score settlement after tipoff"
            if forecasts else
            "Run the private cycle before tipoff to capture eligible fixtures"
            if eligible_for_cycle else
            "Allow the current NBA season to reach five earlier games per team"
        ),
        "bookmaker_odds_verified": False,
        "public_publishing_enabled": False,
        "local_only": True,
        "no_writes": True,
    }


def operations_from_home(home: str | Path, *,
                         now: datetime | None = None) -> dict:
    """Local monitoring; never creates a database nor loads model artifacts."""
    root = Path(home)
    instant = now or datetime.now(timezone.utc)
    games_path = root / "nba_games.jsonl"
    if not games_path.is_file():
        return {
            "status": "research_only", "phase": "stage_2d_first_forecast",
            "operational_state": "missing_local_snapshot",
            "warnings": ["no_local_fixture_snapshot"], "no_writes": True,
            "public_publishing_enabled": False,
        }
    games = read_games(games_path)
    forecasts, last_cycle = _ledger_state(root / "nba_paper.sqlite")
    model_exists, cutoff = _model_cutoff(root)
    prospective = prospective_report(root / "nba_paper.sqlite")
    return build_operations(
        games, forecasts, now=instant, model_exists=model_exists,
        model_cutoff=cutoff, last_cycle=last_cycle,
        prospective=prospective,
    )
