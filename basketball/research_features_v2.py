"""Leakage-safe NBA score-derived experimental features, version 2.

Only information available from prior completed same-season games is used.
No possessions, true pace, offensive rating, injury status or travel mileage
is inferred from scores: those require separately sourced validated data.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from itertools import groupby
from math import sqrt
from statistics import mean

from basketball.research_features import (
    FEATURE_COLUMNS as BASE_FEATURES, make_rows as base_make_rows,
)

VERSION = "nba-score-derived-pregame-v2"
EXTRA_FEATURES = (
    "home_margin_last3", "away_margin_last3",
    "home_total_points_last5", "away_total_points_last5",
    "home_scored_std_last10", "away_scored_std_last10",
    "home_allowed_std_last10", "away_allowed_std_last10",
    "home_games_last4days", "away_games_last4days",
    "home_games_last6days", "away_games_last6days",
    "home_back_to_back_fraction_last10", "away_back_to_back_fraction_last10",
    "home_margin_trend_last5_vs_prev5", "away_margin_trend_last5_vs_prev5",
)
FEATURE_COLUMNS = BASE_FEATURES + EXTRA_FEATURES


def _std(items: list[float]) -> float:
    if len(items) < 2:
        return 0.0
    avg = mean(items)
    return sqrt(sum((v - avg)**2 for v in items)/len(items))


def _recent_features(history: list[dict], target: str) -> tuple[float, ...]:
    recent = history[-10:]
    five = history[-5:]
    last3 = history[-3:]
    today = date.fromisoformat(target)
    if any(date.fromisoformat(g["date"]) >= today for g in recent):
        raise ValueError("NBA feature leakage: non-prior game")
    margins = [g["scored"] - g["allowed"] for g in recent]
    b2b = [
        (date.fromisoformat(recent[i]["date"]) -
         date.fromisoformat(recent[i-1]["date"])).days == 1
        for i in range(1,len(recent))
    ]
    last5_margin = mean(margins[-5:])
    prev5_margin = mean(margins[-10:-5]) if len(margins) >= 10 else last5_margin
    return (
        mean(g["scored"] - g["allowed"] for g in last3),
        mean(g["scored"] + g["allowed"] for g in five),
        _std([g["scored"] for g in recent]),
        _std([g["allowed"] for g in recent]),
        float(sum(date.fromisoformat(g["date"]) >= today-timedelta(days=3)
                  for g in recent)),
        float(sum(date.fromisoformat(g["date"]) >= today-timedelta(days=5)
                  for g in recent)),
        float(sum(b2b)/len(b2b)) if b2b else 0.0,
        last5_margin - prev5_margin,
    )


def make_rows_v2(games: list[dict], min_prior: int = 5) -> list[dict]:
    """Return exactly the v1 eligible cohort with 16 additional as-of features.

    Group by provider game date before updating team history; same-date finals
    MUST NOT be used to predict one another, even with differing UTC tipoffs.
    """
    baseline = base_make_rows(games, min_prior=min_prior)
    by_game = {str(row["game_id"]): row for row in baseline}
    history = defaultdict(list)
    enhanced = {}
    ordered = sorted(games, key=lambda g: (g["date"],str(g["game_id"])))
    for _, batch_iter in groupby(ordered, key=lambda g:g["date"]):
        batch = list(batch_iter)
        for game in batch:
            if game["postseason"]:
                continue
            ident = str(game["game_id"])
            base = by_game.get(ident)
            if base is None:
                continue
            h = history[(game["season"],str(game["home_id"]))]
            a = history[(game["season"],str(game["away_id"]))]
            h_extra = _recent_features(h, game["date"])
            a_extra = _recent_features(a, game["date"])
            extras = tuple(value for pair in zip(h_extra,a_extra) for value in pair)
            enhanced[ident] = {
                **base, "features": tuple(base["features"])+extras,
                "feature_schema": VERSION,
            }
        for game in batch:
            if game["postseason"] or game["status"] != "final":
                continue
            hs, vs = game["home_score"], game["away_score"]
            history[(game["season"],str(game["home_id"]))].append({
                "date": game["date"], "scored": hs, "allowed": vs,
            })
            history[(game["season"],str(game["away_id"]))].append({
                "date": game["date"], "scored": vs, "allowed": hs,
            })
    if len(enhanced) != len(baseline):
        raise ValueError("Candidate features lost previously eligible fixtures")
    if len(FEATURE_COLUMNS) != len(baseline[0]["features"])+len(EXTRA_FEATURES) if baseline else False:
        raise ValueError("Unexpected candidate feature schema")
    return [enhanced[str(row["game_id"])] for row in baseline]
