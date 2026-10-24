"""Explicit, local-only NBA daily research cycle.

Not a web worker, background job or scheduled task. Run via the local CLI.
Retains all model data and paper records in git-ignored private local files.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from basketball.research_data import read_games, write_games
from basketball.research_model import paper_forecasts, train_offline
from basketball.research_readiness import _model_cutoff, build_readiness
from basketball.research_public_data import fetch_public_seasons
from basketball.research_score_only import write_scoreboard_health
from basketball.research_scoreboard import (
    preserve_older_verified_finals, refresh_recent_finals,
)
from basketball.research_store import (
    DEFAULT_DB, latest_events, log_event, open_ledger, performance_report,
    save_forecasts, settle_forecasts,
)

DEFAULT_HOME = Path("data/basketball/research")


def run_cycle(
    *,
    home: str | Path = DEFAULT_HOME,
    start_date: str | None = None,
    days_ahead: int = 2,
    seasons: list[int] | None = None,
    offline: bool = False,
    retrain: bool = False,
    now: datetime | None = None,
) -> dict:
    """Refresh -> optional model fit -> append pregame picks -> settle finals.

    Each execution is explicit; no unattended jobs or production connections.
    The model is only refit on demand or if missing. Never overwrite historical
    paper picks just because model coefficients have changed.
    """
    root = Path(home)
    root.mkdir(parents=True, exist_ok=True)
    model_path = root / "nba_moneyline.joblib"
    data_path = root / "nba_games.jsonl"
    manifest_path = root / "source_manifest.json"
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("The research cycle must use a timezone-aware clock")
    timestamp = timestamp.astimezone(timezone.utc)
    if not 1 <= days_ahead <= 7:
        raise ValueError("Forecast horizon must be 1–7 days")
    first_date = date.fromisoformat(start_date) if start_date else timestamp.date()
    if first_date < timestamp.date() or first_date > timestamp.date() + timedelta(days=7):
        raise ValueError("Cannot construct a backdated or distant paper forecast")
    season_years = seasons or list(range(2017, timestamp.year + 2))
    score_health = {
        "status": "offline", "verified_new_finals": 0,
        "dates_checked": 0, "failed_dates": [],
    }
    restored_historical_finals = 0
    if offline:
        games = read_games(data_path)
    else:
        # Preserve already-verified finals: a delayed GitHub schedule update
        # must not revert them to scheduled or silently change settled scores.
        previous = read_games(data_path) if data_path.is_file() else []
        games, manifest = fetch_public_seasons(season_years)
        games, restored_historical_finals = preserve_older_verified_finals(
            games, previous)
        # Recover unresolved private paper predictions, without creating
        # a new SQLite database before the cycle's normal first-time setup.
        pending_dates = []
        ledger_path = root / "nba_paper.sqlite"
        if ledger_path.is_file():
            with sqlite3.connect(str(ledger_path), timeout=15) as old_db:
                pending_dates = [
                    r[0] for r in old_db.execute(
                        "SELECT DISTINCT f.fixture_date FROM forecasts f "
                        "LEFT JOIN settlements s ON s.game_id=f.game_id "
                        "WHERE s.game_id IS NULL"
                    ).fetchall()
                ]
        games, score_health = refresh_recent_finals(
            games, as_of=timestamp, pending_dates=pending_dates)
        # The snapshot remains atomic and validated. Provider failures
        # produce an explicit partial status, never a fabricated result.
        write_games(games, data_path)
        write_scoreboard_health(root, score_health, timestamp)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8")
    score_model_path = root / "nba_scores.joblib"
    if retrain or not model_path.exists():
        # Trained artifacts remain local; do not upload .joblib to public GitHub.
        metrics = train_offline(games, model_path)
        (root / "training_metrics.json").write_text(
            json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
        )
        trained = True
    else:
        trained = False

    score_trained = False
    if retrain or not score_model_path.exists():
        from basketball.research_market_models import train_score_baselines
        score_metrics = train_score_baselines(games, score_model_path)
        (root / "score_training_metrics.json").write_text(
            json.dumps(score_metrics, indent=2) + "\n", encoding="utf-8")
        score_trained = True

    # Actual private forecast publication is independently gated by the
    # same readiness rules as the read-only UI. A stale fixture snapshot,
    # missing local model/cutoff, future/started game, postseason, or <5
    # earlier same-season games may NEVER become a new paper ledger row.
    model_present, model_cutoff = _model_cutoff(root)
    readiness = build_readiness(
        games, now=timestamp, days_ahead=14,
        model_exists=model_present, model_cutoff=model_cutoff,
    )
    eligible_ids = {
        str(item["game_id"]) for item in readiness["fixtures"]
        if item["eligible"]
    }

    db = open_ledger(root / "nba_paper.sqlite")
    try:
        # A transaction protects writes. Forecasts saved on prior runs are
        # retained unchanged even when the offline model is retrained later.
        existing = {
            row["game_id"] for row in
            db.execute("SELECT game_id FROM forecasts").fetchall()
        }
        inserted = 0
        candidates = 0
        guarded_out = 0
        blocked_examples = []
        eligible_dates = []
        from basketball.research_market_models import private_score_estimates
        for offset in range(days_ahead):
            forecast_day = (first_date + timedelta(days=offset)).isoformat()
            forecasts = paper_forecasts(games, model_path, forecast_day,
                                        as_of=timestamp)
            # Never allow the forecasting model to bypass read-only
            # eligibility gates merely because feature vectors exist.
            disallowed = [f for f in forecasts
                          if str(f["game_id"]) not in eligible_ids]
            guarded_out += len(disallowed)
            blocked_examples.extend(str(f["game_id"]) for f in disallowed[:5])
            forecasts = [f for f in forecasts
                         if str(f["game_id"]) in eligible_ids]
            score_list = private_score_estimates(games, score_model_path,
                                                 forecast_day, as_of=timestamp)
            by_game = {entry["game_id"]: entry for entry in score_list}
            for forecast in forecasts:
                score = by_game.get(forecast["game_id"])
                if score is not None:
                    forecast["expected_total_points"] = score["expected_total_points"]
                    forecast["expected_home_margin"] = score["expected_home_margin"]
            candidates += len(forecasts)
            new_forecasts = [p for p in forecasts if p["game_id"] not in existing]
            if new_forecasts:
                receipt = save_forecasts(db, new_forecasts)
                inserted += receipt["inserted"]
                eligible_dates.append(forecast_day)
                existing.update(p["game_id"] for p in new_forecasts)
        settled = settle_forecasts(db, games)
        if not offline:
            log_event(
                db, "scoreboard",
                f"source={score_health['status']} "
                f"checked={score_health['dates_checked']} "
                f"new_finals={score_health['verified_new_finals']} "
                f"restored={restored_historical_finals} "
                f"failures={len(score_health['failed_dates'])}",
            )
        log_event(
            db, "cycle", f"research_only train={trained} "
            f"fixtures={len(games)} eligible={candidates} "
            f"new_picks={inserted} guard_blocked={guarded_out} "
            f"new_results={settled['newly_settled']}"
        )
        result = {
            "status": "research_only", "date": first_date.isoformat(),
            "generated_at": timestamp.isoformat(), "data_rows": len(games),
            "model_retrained": trained,
            "score_models_retrained": score_trained,
            "eligible_forecasts": candidates,
            "new_forecasts": inserted, "new_dates": eligible_dates,
            "readiness": {
                "snapshot_health": readiness["snapshot"]["status"],
                "eligible_next_14_days": readiness["eligible_forecasts"],
                "readiness_guard_rejected": guarded_out,
                "guarded_fixture_ids": blocked_examples[:5],
            },
            "scoreboard": score_health,
            "restored_historical_finals": restored_historical_finals,
            "settlement": settled, "performance": performance_report(db),
            "next_action": ("Wait for enough earlier same-season games and "
                            "pregame fixtures; no synthetic picks."
                            if candidates == 0 else "Continue paper settlement."),
            "bookmaker_booking_enabled": False, "public_publishing_enabled": False,
            "db_path": str(root / "nba_paper.sqlite"),
            "local_only": True,
        }
        return result
    finally:
        db.close()


def ledger_report(home: str | Path = DEFAULT_HOME) -> dict:
    with open_ledger(Path(home) / "nba_paper.sqlite") as connection:
        return {
            "performance": performance_report(connection),
            "events": latest_events(connection, 10),
            "research_only": True, "public_publishing_enabled": False,
        }
