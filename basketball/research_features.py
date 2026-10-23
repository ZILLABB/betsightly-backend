"""Deterministic, as-of-date NBA features for offline model research.

Only earlier finalized games of the same season contribute to features.
Never use final-score columns of the game being predicted. No randomness.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from itertools import groupby
from statistics import mean

FEATURE_COLUMNS = (
    "home_win_pct_10", "away_win_pct_10",
    "home_scored_10", "home_allowed_10",
    "away_scored_10", "away_allowed_10",
    "home_net_10", "away_net_10",
    "home_rest_days", "away_rest_days",
    "home_last_5_win_pct", "away_last_5_win_pct",
    "home_home_win_pct_10", "away_away_win_pct_10",
)
SCHEMA_VERSION = "nba-pregame-v1"


def _team_form(history: list[dict], target_date: str, venue: str) -> dict:
    recent = history[-10:]
    five = history[-5:]
    venue_games = [item for item in history if item["venue"] == venue][-10:]
    last_date = date.fromisoformat(recent[-1]["date"])
    gap = (date.fromisoformat(target_date) - last_date).days
    if gap <= 0:
        raise ValueError("Feature leakage: same-day or future fixture in history")
    return {
        "win": mean(item["won"] for item in recent),
        "scored": mean(item["scored"] for item in recent),
        "allowed": mean(item["allowed"] for item in recent),
        "net": mean(item["scored"] - item["allowed"] for item in recent),
        "rest": float(min(10, gap - 1)),
        "win_5": mean(item["won"] for item in five),
        "venue_win": (mean(item["won"] for item in venue_games)
                      if venue_games else mean(item["won"] for item in recent)),
    }


def _features(game: dict, history: dict, min_prior: int) -> tuple[float, ...] | None:
    season = game["season"]
    home = history[(season, game["home_id"])]
    away = history[(season, game["away_id"])]
    if len(home) < min_prior or len(away) < min_prior:
        return None
    h = _team_form(home, game["date"], "home")
    a = _team_form(away, game["date"], "away")
    return (
        h["win"], a["win"], h["scored"], h["allowed"],
        a["scored"], a["allowed"], h["net"], a["net"],
        h["rest"], a["rest"], h["win_5"], a["win_5"],
        h["venue_win"], a["venue_win"],
    )


def make_rows(games: list[dict], min_prior: int = 5) -> list[dict]:
    """Produce pregame feature rows, including eligible scheduled games.

    Within each game date, compute all features from the same immutable history
    snapshot; *only afterwards* append that date's completed scores.
    """
    if min_prior < 3:
        raise ValueError("At least 3 prior games required per team")
    history = defaultdict(list)
    result = []
    ordered = sorted(games, key=lambda g: (g["date"], g["game_id"]))
    for _, batch_iter in groupby(ordered, key=lambda g: g["date"]):
        batch = list(batch_iter)
        to_append = []
        for game in batch:
            if game["postseason"]:
                continue  # Separate postseason model required.
            x = _features(game, history, min_prior)
            if x is not None:
                row = {
                    "game_id": game["game_id"], "date": game["date"],
                    "season": game["season"], "home_id": game["home_id"],
                    "away_id": game["away_id"], "home_name": game["home_name"],
                    "away_name": game["away_name"], "status": game["status"],
                    "start_utc": game["start_utc"],
                    "features": x, "source": game["source"],
                }
                if game["status"] == "final":
                    row["home_win"] = int(game["home_score"] > game["away_score"])
                    row["total_points"] = game["home_score"] + game["away_score"]
                    row["home_margin"] = game["home_score"] - game["away_score"]
                result.append(row)
            if game["status"] == "final":
                to_append.append(game)
        for game in to_append:
            h, a = (game["season"], game["home_id"]), (game["season"], game["away_id"])
            hs, vs = game["home_score"], game["away_score"]
            history[h].append({
                "date": game["date"], "won": int(hs > vs),
                "scored": hs, "allowed": vs, "venue": "home",
            })
            history[a].append({
                "date": game["date"], "won": int(vs > hs),
                "scored": vs, "allowed": hs, "venue": "away",
            })
    return result


def quality_report(games: list[dict]) -> dict:
    """Dataset volume/availability diagnostics; no invented coverage claims."""
    seasons = sorted({g["season"] for g in games})
    finals = [g for g in games if g["status"] == "final" and not g["postseason"]]
    rows = make_rows(games)
    training = [row for row in rows if row["status"] == "final"]
    per_season = defaultdict(Counter)
    for game in games:
        per_season[game["season"]][game["status"]] += 1
    return {
        "source": sorted({g["source"] for g in games}),
        "seasons": seasons,
        "games_by_season": {str(season): dict(per_season[season])
                            for season in seasons},
        "games": len(games),
        "completed_regular_games": len(finals),
        "eligible_model_rows": len(training),
        "scheduled_paper_fixtures": sum(row["status"] == "scheduled" for row in rows),
        "min_prior_games": 5,
        "feature_schema_version": SCHEMA_VERSION,
        "markets_supported": ["nba_moneyline"],
        "bookmaker_odds_present": False,
        "commercial_use_review_required": True,
    }
