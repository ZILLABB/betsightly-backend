"""Read-only readiness diagnostics for the private NBA research lab.

The feature gate mirrors research_features.make_rows: a team's history uses
only FINAL regular-season games from strictly earlier game dates in the same
season. This module never estimates an outcome, retrains or publishes picks.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from basketball.research_data import read_games

MAX_SNAPSHOT_AGE_HOURS = 36
REASONS = {
    "home_warmup": "Home team has fewer than five earlier same-season finals",
    "away_warmup": "Away team has fewer than five earlier same-season finals",
    "missing_tipoff": "Verified UTC tipoff is missing or invalid",
    "started": "Fixture has already started",
    "postseason": "Separate postseason model required",
    "source_stale": "Source snapshot is older than 36 hours",
    "source_missing": "No locally verified source snapshot",
    "source_invalid": "Local source snapshot failed validation",
    "source_clock_skew": "Snapshot has a future retrieval timestamp",
    "model_missing": "Moneyline model is not trained locally",
    "model_metadata_missing": "Trained model cutoff metadata is unavailable",
    "model_cutoff": "Fixture is not later than model training cutoff",
}


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _clock(now: datetime | None) -> datetime:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Readiness requires a timezone-aware clock")
    return instant.astimezone(timezone.utc)


def _snapshot_health(games: list[dict], now: datetime) -> dict:
    stamps = [_timestamp(g.get("retrieved_at")) for g in games]
    valid = [stamp for stamp in stamps if stamp is not None]
    if not valid:
        return {"status": "unknown", "last_retrieved_at": None,
                "age_hours": None, "source": sorted({g["source"] for g in games})}
    most_recent = max(valid)
    hours = (now - most_recent).total_seconds() / 3600
    status = ("clock_skew" if hours < -5/60 else
              "stale" if hours > MAX_SNAPSHOT_AGE_HOURS else "fresh")
    return {"status": status, "last_retrieved_at": most_recent.isoformat(),
            "age_hours": round(hours, 2),
            "source": sorted({g["source"] for g in games})}


def _model_cutoff(home: Path) -> tuple[bool, str | None]:
    model_exists = (home / "nba_moneyline.joblib").is_file()
    metrics_path = home / "training_metrics.json"
    if not model_exists or not metrics_path.is_file():
        return model_exists, None
    try:
        value = json.loads(metrics_path.read_text(encoding="utf-8"))
        cutoff = value["prospective_refit"]["through"]
        datetime.strptime(cutoff, "%Y-%m-%d")
        return True, cutoff
    except (OSError, ValueError, TypeError, KeyError):
        return True, None


def build_readiness(
    games: list[dict], *,
    now: datetime | None = None,
    days_ahead: int = 7,
    model_exists: bool = True,
    model_cutoff: str | None = None,
) -> dict:
    """Summarize next N*24h, with earlier-day season counts, never future labels.

    model_cutoff=None is an explicit blocker when model_exists=True: the
    readiness view cannot certify a model without verified cutoff metadata.
    """
    if not 1 <= days_ahead <= 14:
        raise ValueError("Readiness horizon must be 1 to 14 days")
    instant = _clock(now)
    expiry = instant + timedelta(days=days_ahead)
    source = _snapshot_health(games, instant)
    history = defaultdict(Counter)
    ordered = sorted(games, key=lambda g: (g["date"], str(g["game_id"])))
    grouped = defaultdict(list)
    for game in ordered:
        grouped[game["date"]].append(game)

    fixtures = []
    for game_day in sorted(grouped):
        batch = grouped[game_day]
        # Identical to feature engineering: inspect each date BEFORE appending
        # its finals. Same-day games cannot become each other's prior history.
        for game in batch:
            if game["status"] != "scheduled":
                continue
            kickoff = _timestamp(game.get("start_utc"))
            # Include missing-tipoff scheduled fixtures by their provider date,
            # but never silently treat their calendar date as a valid kickoff.
            if kickoff is None:
                try:
                    match_day = datetime.strptime(game["date"], "%Y-%m-%d").date()
                except ValueError:
                    continue
                if not instant.date() <= match_day <= expiry.date():
                    continue
            elif not instant <= kickoff <= expiry:
                # Already-started fixtures of the current UTC date are useful
                # diagnostics, not valid forecasts; include today's fixtures.
                if not (kickoff < instant and
                        kickoff.date() == instant.date()):
                    continue

            home = history[(game["season"], str(game["home_id"]))]
            away = history[(game["season"], str(game["away_id"]))]
            h_count = sum(home.values())
            a_count = sum(away.values())
            reasons = []
            if game.get("postseason"):
                reasons.append("postseason")
            if h_count < 5:
                reasons.append("home_warmup")
            if a_count < 5:
                reasons.append("away_warmup")
            if kickoff is None:
                reasons.append("missing_tipoff")
            elif kickoff <= instant:
                reasons.append("started")
            if source["status"] != "fresh":
                reasons.append({
                    "stale": "source_stale",
                    "clock_skew": "source_clock_skew",
                }.get(source["status"], "source_invalid"))
            if not model_exists:
                reasons.append("model_missing")
            elif not model_cutoff:
                reasons.append("model_metadata_missing")
            elif game["date"] <= model_cutoff:
                reasons.append("model_cutoff")

            fixtures.append({
                "game_id": str(game["game_id"]),
                "date": game["date"], "start_utc": game.get("start_utc"),
                "season": game["season"],
                "home_team": game["home_name"],
                "away_team": game["away_name"],
                "home_prior_games": h_count, "away_prior_games": a_count,
                "home_games_remaining": max(0, 5 - h_count),
                "away_games_remaining": max(0, 5 - a_count),
                "feature_ready": not ({"home_warmup", "away_warmup", "postseason"}
                                     & set(reasons)),
                "eligible": not reasons,
                "reasons": reasons,
                "source": game["source"],
            })
        for game in batch:
            if game["status"] == "final" and not game.get("postseason"):
                # The same feature model only ingests completed games,
                # with date-ordered batches; no synthetic/current fixtures.
                history[(game["season"], str(game["home_id"]))]["final"] += 1
                history[(game["season"], str(game["away_id"]))]["final"] += 1

    fixtures.sort(key=lambda g: (g["start_utc"] or g["date"],
                                 g["game_id"]))
    reasons = Counter(reason for fixture in fixtures
                      for reason in fixture["reasons"])
    return {
        "status": "research_only", "generated_at": instant.isoformat(),
        "days_ahead": days_ahead, "snapshot": source,
        "source_games": len(games),
        "scheduled_fixtures": len(fixtures),
        "feature_ready": sum(f["feature_ready"] for f in fixtures),
        "eligible_forecasts": sum(f["eligible"] for f in fixtures),
        "blockers": dict(sorted(reasons.items())),
        "reason_labels": REASONS,
        "model": {"present": model_exists, "training_cutoff": model_cutoff},
        "fixtures": fixtures,
        "public_publishing_enabled": False,
        "bookmaker_booking_enabled": False,
    }


def readiness_from_home(home: str | Path, *, days_ahead: int = 7,
                        now: datetime | None = None) -> dict:
    """Local diagnostics. No downloads, no writes, no unpickling."""
    path = Path(home)
    model_exists, cutoff = _model_cutoff(path)
    data = path / "nba_games.jsonl"
    if not data.is_file():
        report = build_readiness([], now=now, days_ahead=days_ahead,
                                 model_exists=model_exists, model_cutoff=cutoff)
        report["snapshot"]["status"] = "missing"
        return report
    try:
        games = read_games(data)
    except (ValueError, OSError, TypeError):
        report = build_readiness([], now=now, days_ahead=days_ahead,
                                 model_exists=model_exists, model_cutoff=cutoff)
        report["snapshot"]["status"] = "invalid"
        return report
    return build_readiness(games, now=now, days_ahead=days_ahead,
                           model_exists=model_exists, model_cutoff=cutoff)
