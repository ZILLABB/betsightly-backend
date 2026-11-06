"""Read-only NBA Cup final source-classification and shadow sensitivity audit.

The 2025 Cup final NYK 124-113 SAS was NON-STANDINGS. Data providers may
mislabel that official event as 'regular season'; detect only an exact match.
Never silently edit source files, retroactively mutate before-tipoff evidence,
or release modified probabilities as verified or bookmaker-ready forecasts.

References:
 https://www.nba.com/game/sas-vs-nyk-0062500001
 https://www.cbsnews.com/newyork/news/knicks-beat-spurs-nba-cup/
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from basketball.research_data import read_games
from basketball.research_coldstart import candidates, _now
from basketball.research_readiness import _timestamp
from basketball.research_coldstart_ops import calendar_anomalies

CUP_SEASON = 2026
CUP_HOME = "New York Knicks"
CUP_AWAY = "San Antonio Spurs"
CUP_FINAL_DATE = "2025-12-16"
CUP_SCORE = (124, 113)
OFFICIAL_GAME_URL = "https://www.nba.com/game/sas-vs-nyk-0062500001"


def identify_cup_final(games):
    """Only the exact 2025 NBA Cup final fixture identity is sufficient."""
    found = []
    for g in games:
        if (int(g["season"]) != CUP_SEASON or g["status"] != "final"
            or g["postseason"]):
            continue
        # ESPN NBA game_date can be American local or UTC; accept ONLY
        # matching event teams, exact known score and either date.
        if (g["date"] not in ("2025-12-16", "2025-12-17")
            or g["home_name"].strip().casefold() != CUP_HOME.casefold()
            or g["away_name"].strip().casefold() != CUP_AWAY.casefold()
            or (g["home_score"], g["away_score"]) != CUP_SCORE):
            continue
        stamp = _timestamp(g.get("start_utc"))
        if stamp is None or not (datetime(2025, 12, 16, 0,
                                         tzinfo=timezone.utc)
                                 <= stamp < datetime(2025, 12, 18, 0,
                                                    tzinfo=timezone.utc)):
            continue
        found.append(g)
    if len(found) > 1:
        return "ambiguous_multiple_matches", []
    return ("matched_verified_event" if len(found) == 1
            else "not_identified_in_local_source"), found


def review(games, *, now=None):
    instant = _now(now)
    event_status, cup = identify_cup_final(games)
    raw = calendar_anomalies(games, season=CUP_SEASON)
    corrected = None
    if event_status == "matched_verified_event":
        gid = str(cup[0]["game_id"])
        # In-memory only; never change the downloaded provider snapshot.
        sanitized = [g for g in games if str(g["game_id"]) != gid]
        corrected = calendar_anomalies(sanitized, season=CUP_SEASON)
        active = candidates(games, now=instant)
        alternative = candidates(sanitized, now=instant)
        alt_map = {r["game_id"]: r for r in alternative}
        compare = []
        for item in active:
            other = alt_map.get(item["game_id"])
            if other is None:
                continue
            if (item["home_id"], item["away_id"],
                item["start_utc"]) != (
                other["home_id"], other["away_id"],
                other["start_utc"]):
                raise ValueError("Counterfactual NBA match identity mismatch")
            difference = round(
                other["probability_home_win"] - item["probability_home_win"], 6)
            compare.append({
                "game_id": item["game_id"],
                "home": item["home_team"], "away": item["away_team"],
                "tipoff_utc": item["start_utc"],
                "original_experimental_probability": item["probability_home_win"],
                "nonstandings_excluded_probability": other["probability_home_win"],
                "probability_delta": difference,
            })
        sensitivity = {
            "comparisons": len(compare),
            "changed": sum(abs(v["probability_delta"]) > 0 for v in compare),
            "maximum_absolute_delta": (
                max(abs(v["probability_delta"]) for v in compare)
                if compare else None),
            "mean_absolute_delta": (
                round(sum(abs(v["probability_delta"]) for v in compare)
                      / len(compare), 6) if compare else None),
            "future_fixture_examples": compare[:16],
            "not_reprocessing_already_started_forecasts": True,
            "no_candidate_predictions_published": True,
        }
    else:
        sensitivity = {
            "status": "not_computed_without_exact_confirmed_source_game",
            "comparisons": 0, "changed": None,
            "future_fixture_examples": [],
        }
    return {
        "status": "review_only" if event_status != "ambiguous_multiple_matches"
                  else "integrity_blocked",
        "historical_event": "2025 NBA Cup final NYK 124 - SAS 113",
        "season": CUP_SEASON,
        "cup_fixture_identification": event_status,
        "cup_final_source_game_id": (
            str(cup[0]["game_id"]) if cup else None),
        "cup_game_is_not_in_standings": True,
        "official_game_url": OFFICIAL_GAME_URL,
        "raw_season_calendar": raw,
        "counterfactual_calendar_after_excluding_nonstandings": corrected,
        "active_future_shadow_sensitivity": sensitivity,
        "already_recorded_predictions_left_untouched": True,
        "trusted_v1_changed": False,
        "retrospective_metrics_replaced": False,
        "not_bookable": True,
        "research_only": True,
        "no_writes": True,
        "model_promotion_approved": False,
        "source_provenance_review_required": True,
    }


def from_home(home, *, now=None):
    file = Path(home) / "nba_games.jsonl"
    if not file.is_file():
        return {"status": "source_missing", "no_writes": True,
                "research_only": True}
    return review(read_games(file), now=now)
