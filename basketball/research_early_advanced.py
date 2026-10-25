"""NBA early-season *prior-year advanced* score research, no new data provider.

Existing same-season advanced models cannot predict 0–4 earlier-season
games: all features need 5 current-season finals. This fixed-form alternative
uses only the last 12 paired team boxscores from the *completed previous
season*, plus at most 4 earlier-day current-season games. It is independent
of the existing moneyline and score forecast ledgers. No betting advice.
"""
from __future__ import annotations

import math
from collections import defaultdict
from itertools import groupby
from pathlib import Path

from basketball.research_advanced_features import _prepare, _load_json
from basketball.research_coldstart import _now
from basketball.research_data import read_games
from basketball.research_opening_score import (
    _corrected, candidates as base_candidates, _metrics, TARGETS,
)

VERSION = "nba-cross-season-advanced-points-research-v1"
PRIOR_WINDOW = 12
MIN_PREVIOUS_BOX_GAMES = 8
CURRENT_WEIGHT_PSEUDOGAMES = 12
EDGE_POINTS = 1.5


def _box_snapshot(home):
    root = Path(home)
    raw = read_games(root / "nba_games.jsonl")
    games = _corrected(raw)
    files = root / "advanced"
    team, seasons = [], []
    for year in sorted({int(g["season"]) for g in games}):
        p = files / f"team_{year}.json"
        if p.is_file():
            team.extend(_load_json(p))
            seasons.append(year)
    # The exact existing box-score authority checks scores and opponent IDs.
    paired, _ = _prepare(games, team, [])
    return games, paired, seasons


def _observation(game, paired):
    """Do not fabricate pace/efficiency when one verified side is absent."""
    gid = str(game["game_id"])
    hid, aid = str(game["home_id"]), str(game["away_id"])
    h, a = paired.get((gid, hid)), paired.get((gid, aid))
    if h is None or a is None:
        return None
    vals = (
        h["estimated_possessions"], a["estimated_possessions"],
        h["estimated_offensive_rating"], a["estimated_offensive_rating"],
    )
    if (any(not isinstance(v, (float, int)) or isinstance(v, bool)
            or not math.isfinite(v) for v in vals)
        or not 30 <= min(vals[:2]) <= max(vals[:2]) <= 180
        or min(vals[2:]) <= 0 or max(vals[2:]) >= 250):
        raise ValueError("Invalid verified NBA advanced efficiency")
    return (
        (vals[0], vals[2], vals[3]),
        (vals[1], vals[3], vals[2]),
    )


def _team_strength(previous, current):
    if len(previous) < MIN_PREVIOUS_BOX_GAMES:
        return None
    past = previous[-PRIOR_WINDOW:]
    if len(current) > 4:
        # Only the early-season experiment is supported here.
        return None
    def average(index):
        older = sum(row[index] for row in past)/len(past)
        newest = sum(row[index] for row in current)
        return (CURRENT_WEIGHT_PSEUDOGAMES*older+newest)/(
            CURRENT_WEIGHT_PSEUDOGAMES+len(current))
    return tuple(average(i) for i in range(3))


def projections(games, paired, *, now=None, historical=False):
    """Compare ONLY original early-season eligible fixtures, same game IDs.

    Entire prior-season finals are admissible, but the current-season lookup
    is updated only *after* all fixtures of each source date were evaluated.
    """
    instant = _now(now)
    baseline = base_candidates(
        games, now=instant, historical=historical)
    by_identity = {(int(r["season"]), str(r["game_id"])): r
                   for r in baseline}
    ordered = sorted(games, key=lambda g: (
        int(g["season"]), g["date"], str(g["game_id"])))
    prev_history = defaultdict(list)
    for game in ordered:
        if game["status"] != "final" or game["postseason"]:
            continue
        observations = _observation(game, paired)
        if observations is None:
            continue
        season = int(game["season"])
        prev_history[(season, str(game["home_id"]))].append(
            (game["date"], game["game_id"], observations[0]))
        prev_history[(season, str(game["away_id"]))].append(
            (game["date"], game["game_id"], observations[1]))
    # Last games of previous season (not just whichever source order).
    prev_history = {key: [
        x[2] for x in sorted(items, key=lambda r: (r[0], str(r[1])))]
        for key, items in prev_history.items()}
    current = defaultdict(list)
    created = []
    for (season, _), group in groupby(
        ordered, key=lambda g: (int(g["season"]), g["date"])
    ):
        daily = list(group)
        for game in daily:
            original = by_identity.get((season, str(game["game_id"])))
            if original is None:
                continue
            h, a = str(game["home_id"]), str(game["away_id"])
            home = _team_strength(
                prev_history.get((season-1, h), []),
                current[(season, h)])
            away = _team_strength(
                prev_history.get((season-1, a), []),
                current[(season, a)])
            if home is None or away is None:
                continue
            possession_estimate = (home[0]+away[0])/2
            projected_home = (
                possession_estimate*(home[1]+away[2])/200+EDGE_POINTS)
            projected_away = (
                possession_estimate*(away[1]+home[2])/200-EDGE_POINTS)
            projected_total = projected_home + projected_away
            if (not 130 <= projected_total <= 350 or
                not 55 <= projected_home <= 180 or
                not 55 <= projected_away <= 180):
                continue
            entry = {
                **original,
                "predicted_home_points": round(projected_home,4),
                "predicted_away_points": round(projected_away,4),
                "predicted_total": round(projected_total,4),
                "predicted_home_margin": round(projected_home-projected_away,4),
                "reference_model": original["model_version"],
                "reference_predicted_total": original["predicted_total"],
                "reference_predicted_home_margin": original["predicted_home_margin"],
                "reference_predicted_home_points": original["predicted_home_points"],
                "reference_predicted_away_points": original["predicted_away_points"],
                "previous_home_boxscore_games": len(
                    prev_history[(season-1,h)]),
                "previous_away_boxscore_games": len(
                    prev_history[(season-1,a)]),
                "earlier_current_home_boxscore_games": len(
                    current[(season,h)]),
                "earlier_current_away_boxscore_games": len(
                    current[(season,a)]),
                "estimated_possessions": round(possession_estimate,4),
                "model_version": VERSION,
                "no_bookmaker_market_or_prices": True,
            }
            created.append(entry)
        for game in daily:
            if game["status"] != "final" or game["postseason"]:
                continue
            obs = _observation(game, paired)
            if obs is None:
                continue
            current[(season, str(game["home_id"]))].append(obs[0])
            current[(season, str(game["away_id"]))].append(obs[1])
    return sorted(created, key=lambda r:(r["start_utc"],r["game_id"])), len(baseline)


def _comparison(rows):
    result = {"matched_games": len(rows), "targets": {}}
    for target,pred,baseline,actual in TARGETS:
        if not rows:
            result["targets"][target] = {
                "advanced_mae": None, "reference_early_score_mae": None,
                "advanced_minus_reference_mae": None,
                "advanced_rmse": None, "advanced_bias": None}
            continue
        reference = "reference_"+pred
        advance_errors = [r[pred]-r[actual] for r in rows]
        reference_errors = [r[reference]-r[actual] for r in rows]
        n = len(rows)
        av = sum(abs(v) for v in advance_errors)/n
        rv = sum(abs(v) for v in reference_errors)/n
        result["targets"][target] = {
            "advanced_mae": round(av,4),
            "reference_early_score_mae": round(rv,4),
            "advanced_minus_reference_mae": round(av-rv,4),
            "advanced_rmse": round(math.sqrt(
                sum(v*v for v in advance_errors)/n),4),
            "advanced_bias": round(sum(advance_errors)/n,4),
        }
    return result


def benchmark(home, *, now=None):
    games, paired, seasons = _box_snapshot(home)
    historical, basic_count = projections(
        games, paired, now=now, historical=True)
    new_rows, current_basic = projections(
        games, paired, now=now, historical=False)
    seasons_report = {}
    for season in (2025, 2026):
        target = [row for row in historical if row["season"] == season]
        seasons_report[str(season)] = _comparison(target)
    return {
        "status": "retrospective_diagnostic_only", "version": VERSION,
        "historical_matched": _comparison(historical),
        "historical_years": seasons_report,
        "original_historical_early_score_eligible": basic_count,
        "available_prior_year_team_assets": seasons,
        "future_before_tipoff_eligible": len(new_rows),
        "original_future_early_score_eligible": current_basic,
        "future_preview_samples": [{
            "game_id": r["game_id"],
            "start_utc": r["start_utc"],
            "home": r["home_team"], "away": r["away_team"],
            "estimate_total_points": r["predicted_total"],
            "reference_estimate_total_points": r["reference_predicted_total"],
            "estimated_possessions": r["estimated_possessions"],
        } for r in new_rows[:12]],
        "matched_game_only_comparison": True,
        "advanced_model_is_last_season_teams_not_live_lineups": True,
        "no_injury_player_or_sportsbook_data": True,
        "no_2027_score_labels_used_for_selection": True,
        "no_new_prospective_forecasts_recorded": True,
        "model_promoted": False,
        "no_writes": True, "research_only": True, "not_bookable": True,
    }
