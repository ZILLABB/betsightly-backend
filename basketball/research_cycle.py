"""Explicit, local-only NBA daily research cycle.

Not a web worker, background job or scheduled task. Run via the local CLI.
Retains all model data and paper records in git-ignored private local files.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from basketball.research_data import read_games, write_games
from basketball.research_model import paper_forecasts, train_offline
from basketball.research_public_data import fetch_public_seasons
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
    if offline:
        games = read_games(data_path)
    else:
        games, manifest = fetch_public_seasons(season_years)
        write_games(games, data_path)
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
        eligible_dates = []
        for offset in range(days_ahead):
            forecast_day = (first_date + timedelta(days=offset)).isoformat()
            forecasts = paper_forecasts(games, model_path, forecast_day,
                                        as_of=timestamp)
            candidates += len(forecasts)
            new_forecasts = [p for p in forecasts if p["game_id"] not in existing]
            if new_forecasts:
                receipt = save_forecasts(db, new_forecasts)
                inserted += receipt["inserted"]
                eligible_dates.append(forecast_day)
                existing.update(p["game_id"] for p in new_forecasts)
        settled = settle_forecasts(db, games)
        log_event(
            db, "cycle", f"research_only train={trained} "
            f"fixtures={len(games)} eligible={candidates} "
            f"new_picks={inserted} new_results={settled['newly_settled']}"
        )
        result = {
            "status": "research_only", "date": first_date.isoformat(),
            "generated_at": timestamp.isoformat(), "data_rows": len(games),
            "model_retrained": trained,
            "score_models_retrained": score_trained,
            "eligible_forecasts": candidates,
            "new_forecasts": inserted, "new_dates": eligible_dates,
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
