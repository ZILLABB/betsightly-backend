"""Shared deterministic Elo contract for live and offline football features."""
from __future__ import annotations

from collections import defaultdict

ELO_CORE_VERSION = "betsightly-runtime-elo-core-v1"
DEFAULT_RATING = 1500.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
MIN_MATCHES = 3
HISTORY_DAYS = 240


def expected_home(home_rating: float, away_rating: float, *, neutral: bool = False) -> float:
    advantage = 0.0 if neutral else HOME_ADVANTAGE
    diff = float(home_rating) + advantage - float(away_rating)
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def goal_difference_multiplier(home_score: int, away_score: int) -> float:
    gd = abs(int(home_score) - int(away_score))
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return 1.75 + (gd - 3) / 8.0


def update_pair(
    home_rating: float,
    away_rating: float,
    home_score: int,
    away_score: int,
    *,
    neutral: bool = False,
) -> tuple[float, float]:
    expectation = expected_home(home_rating, away_rating, neutral=neutral)
    actual = (
        1.0 if int(home_score) > int(away_score)
        else 0.5 if int(home_score) == int(away_score)
        else 0.0
    )
    delta = (
        K_FACTOR
        * goal_difference_multiplier(home_score, away_score)
        * (actual - expectation)
    )
    return float(home_rating) + delta, float(away_rating) - delta


def run_elo(matches: list[dict]) -> tuple[dict[str, float], dict[str, int]]:
    ratings: dict[str, float] = defaultdict(lambda: DEFAULT_RATING)
    counts: dict[str, int] = defaultdict(int)

    for match in matches:
        home = str(match["home"])
        away = str(match["away"])
        home_rating, away_rating = update_pair(
            ratings[home],
            ratings[away],
            int(match["hs"]),
            int(match["as"]),
            neutral=bool(match.get("neutral")),
        )
        ratings[home] = home_rating
        ratings[away] = away_rating
        counts[home] += 1
        counts[away] += 1

    return dict(ratings), dict(counts)


def feature_snapshot(
    home_rating: float | None,
    away_rating: float | None,
    home_matches: int,
    away_matches: int,
    *,
    neutral: bool = False,
) -> dict:
    evidence = min(int(home_matches or 0), int(away_matches or 0))
    advantage = 0.0 if neutral else HOME_ADVANTAGE
    if home_rating is None or away_rating is None or evidence < MIN_MATCHES:
        return {
            "status": "UNAVAILABLE",
            "elo_available": 0.0,
            "elo_home_expectation": 0.5,
            "elo_diff_scaled": 0.0,
            "elo_evidence_scaled": 0.0,
            "rating_evidence": evidence,
            "home_advantage_applied": advantage,
        }

    diff = float(home_rating) + advantage - float(away_rating)
    return {
        "status": "READY",
        "elo_available": 1.0,
        "elo_home_expectation": expected_home(
            float(home_rating), float(away_rating), neutral=neutral
        ),
        "elo_diff_scaled": max(-1.0, min(1.0, diff / 600.0)),
        "elo_evidence_scaled": min(1.0, evidence / 20.0),
        "rating_evidence": evidence,
        "home_advantage_applied": advantage,
    }


def three_way_probabilities(
    home_rating: float,
    away_rating: float,
    *,
    neutral: bool = False,
) -> dict:
    advantage = 0.0 if neutral else HOME_ADVANTAGE
    diff = float(home_rating) + advantage - float(away_rating)
    expected = expected_home(home_rating, away_rating, neutral=neutral)
    draw = max(0.10, min(0.30, 0.30 - abs(diff) / 1500.0))
    home = max(0.05, expected - 0.5 * draw)
    away = max(0.05, 1.0 - home - draw)
    total = home + draw + away
    return {
        "home_win": round(home / total, 4),
        "draw": round(draw / total, 4),
        "away_win": round(away / total, 4),
        "home_advantage_applied": advantage,
    }
