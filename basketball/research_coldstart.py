"""Isolated NBA opening-week empirical-prior shadow study.

Unlike trusted v1 (five earlier same-season finals per club), this uses a
published prior-season record and zero to four earlier current-season finals.
Its fixed-form coefficients are RESEARCH heuristics, not a fitted, validated
betting edge. All forecasts are prospective, append-only and nonbookable.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path

from basketball.research_data import APPROVED_RESEARCH_SOURCES, read_games
from basketball.research_readiness import _snapshot_health, _timestamp

VERSION = "nba-coldstart-empirical-prior-shadow-v1"
FILENAME = "coldstart_forecasts.jsonl"
RESULTS = "coldstart_settlements.jsonl"
MIN_PREVIOUS = 20
MAX_EARLIER = 4
PREGAME_BUFFER_MINUTES = 10


def _now(value):
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("An aware UTC NBA clock is mandatory")
    return instant.astimezone(timezone.utc)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _signed(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _previous_season(games):
    records = defaultdict(lambda: [0, 0])
    home = defaultdict(lambda: [0, 0])
    for g in games:
        if g["status"] != "final" or g["postseason"]:
            continue
        season = int(g["season"])
        h, a = str(g["home_id"]), str(g["away_id"])
        hw = int(g["home_score"] > g["away_score"])
        records[(season, h)][0] += hw
        records[(season, h)][1] += 1
        records[(season, a)][0] += (1 - hw)
        records[(season, a)][1] += 1
        home[season][0] += hw
        home[season][1] += 1
    return records, home


def _prob(prior, current, home_advantage):
    # The prior-season empirical-Bayes strength and fixed 20-game shrinkage
    # keep early-season outcomes from swinging probabilities excessively.
    p0 = (prior[0] + 10) / (prior[1] + 20)
    p = (current[0] + 20 * p0) / (current[1] + 20)
    if not 0 < p < 1:
        raise ValueError("Invalid cold-start strength")
    return p


def candidates(games, *, now=None, historical=False, seasons=(2025, 2026)):
    """Build pregame features before incorporating ANY final on the same date.

    Historical mode scores completed matches of specified seasons only.
    Prospective mode scans 48h of future scheduled UTC-tipoff fixtures.
    """
    instant = _now(now)
    previous, home_record = _previous_season(games)
    current = defaultdict(lambda: [0, 0])
    rows = []
    ordered = sorted(games, key=lambda g: (int(g["season"]), g["date"], str(g["game_id"])))
    for (_, _), group in groupby(ordered, key=lambda g: (int(g["season"]), g["date"])):
        day = list(group)
        for game in day:
            if game["postseason"]:
                continue
            status = game["status"]
            if historical:
                if status != "final" or int(game["season"]) not in seasons:
                    continue
            elif status != "scheduled":
                continue
            tipoff = _timestamp(game.get("start_utc"))
            if tipoff is None:
                continue
            if not historical and not (
                instant + timedelta(minutes=PREGAME_BUFFER_MINUTES)
                < tipoff <= instant + timedelta(hours=48)
            ):
                continue
            season = int(game["season"])
            h, a = str(game["home_id"]), str(game["away_id"])
            hp = previous.get((season - 1, h), (0, 0))
            ap = previous.get((season - 1, a), (0, 0))
            hc = current[(season, h)]
            ac = current[(season, a)]
            if hp[1] < MIN_PREVIOUS or ap[1] < MIN_PREVIOUS:
                continue  # No unverified expansion-team / old-season proxy.
            if hc[1] > MAX_EARLIER and ac[1] > MAX_EARLIER:
                continue  # Entrust fully warmed-up fixtures to v1.
            base_record = home_record[season - 1]
            if base_record[1] < 200:
                continue
            home_p = max(0.4, min(0.65, (base_record[0] + 50) /
                                  (base_record[1] + 100)))
            home_strength = _prob(hp, hc, home_p)
            away_strength = _prob(ap, ac, home_p)
            logit = math.log(home_p / (1 - home_p))
            # Conservative difference; not a trained bookmaker-market model.
            score = logit + 1.5 * (home_strength - away_strength)
            probability = round(max(0.25, min(0.75,
                                1 / (1 + math.exp(-score)))), 6)
            rows.append({
                "game_id": str(game["game_id"]),
                "date": game["date"],
                "season": season,
                "start_utc": tipoff.isoformat(),
                "home_id": h, "away_id": a,
                "home_team": game["home_name"],
                "away_team": game["away_name"],
                "prior_home_games": hp[1], "prior_away_games": ap[1],
                "current_home_games": hc[1], "current_away_games": ac[1],
                "probability_home_win": probability,
                "previous_season_home_baseline": round(home_p, 6),
                "model_version": VERSION,
                "source": game["source"],
            } | ({"actual_home_win": int(game["home_score"] > game["away_score"])}
                 if historical else {}))
        # Update ONLY after scoring all fixtures of the same NBA provider day.
        for game in day:
            if game["status"] != "final" or game["postseason"]:
                continue
            season = int(game["season"])
            h, a = str(game["home_id"]), str(game["away_id"])
            hw = int(game["home_score"] > game["away_score"])
            current[(season, h)][0] += hw
            current[(season, h)][1] += 1
            current[(season, a)][0] += 1 - hw
            current[(season, a)][1] += 1
    return sorted(rows, key=lambda r: (r["start_utc"], r["game_id"]))


def _paired_metrics(rows):
    """Equal-cohort probabilistic diagnostics; no realized betting returns."""
    n = len(rows)
    if n == 0:
        return {"games": 0, "candidate_brier": None,
                "prior_home_baseline_brier": None, "paired_brier_improvement": None,
                "candidate_log_loss": None, "baseline_log_loss": None,
                "candidate_accuracy": None, "observed_home_win_rate": None,
                "candidate_mean_probability": None,
                "candidate_calibration": []}
    def brier(key):
        return sum((r[key] - r["actual_home_win"]) ** 2 for r in rows) / n
    def logloss(key):
        return -sum(
            r["actual_home_win"] * math.log(max(1e-12, min(1-1e-12, r[key]))) +
            (1-r["actual_home_win"]) *
            math.log(max(1e-12, min(1-1e-12, 1-r[key])))
            for r in rows
        ) / n
    cand = brier("probability_home_win")
    baseline = brier("previous_season_home_baseline")
    bins = []
    for i in range(5):
        lower, upper = i/5, (i+1)/5
        selected = [r for r in rows
                    if lower <= r["probability_home_win"] < upper or
                    (i == 4 and r["probability_home_win"] == 1)]
        bins.append({
            "lower": lower, "upper": upper, "games": len(selected),
            "mean_forecast": (round(sum(r["probability_home_win"] for r in selected)
                             /len(selected), 6) if selected else None),
            "observed_home_wins": (round(sum(r["actual_home_win"] for r in selected)
                                   /len(selected), 6) if selected else None),
            "small_sample": len(selected) < 30,
        })
    return {
        "games": n,
        "candidate_brier": round(cand, 6),
        "prior_home_baseline_brier": round(baseline, 6),
        "paired_brier_improvement": round(baseline - cand, 6),
        "candidate_log_loss": round(logloss("probability_home_win"), 6),
        "baseline_log_loss": round(logloss("previous_season_home_baseline"), 6),
        "candidate_accuracy": round(sum(
            (r["probability_home_win"] >= .5) == bool(r["actual_home_win"])
            for r in rows) / n, 6),
        "observed_home_win_rate": round(sum(
            r["actual_home_win"] for r in rows) / n, 6),
        "candidate_mean_probability": round(sum(
            r["probability_home_win"] for r in rows) / n, 6),
        "candidate_calibration": bins,
    }


def benchmark(games):
    rows = candidates(games, historical=True)
    folds = {str(year): _paired_metrics(
        [r for r in rows if r["season"] == year])
             for year in (2025, 2026)}
    return {
        "status": "research_only", "method": VERSION,
        "strictly_earlier_date_history": True,
        "same_season_games_required": "at least one club has fewer than five",
        "walkforward_folds": folds,
        "pooled": _paired_metrics(rows),
        "historical_tuning_disclosure": (
            "Heuristic fixed before this analysis but retrospective tests "
            "are not untouched prospective validation; smaller bins are noisy."
        ),
        "model_retrained": False, "trusted_v1_changed": False,
        "commercial_use_cleared": False, "no_writes": True,
        "bookmaker_odds_verified": False,
    }


def readiness(home, *, now=None):
    """No writes: explain whether opening-week real capture is possible now."""
    instant = _now(now)
    path = Path(home) / "nba_games.jsonl"
    if not path.is_file():
        return {"status": "source_missing", "eligible_next_48h": 0,
                "upcoming_next_48h": 0, "research_only": True, "no_writes": True}
    try:
        games = read_games(path)
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "source_invalid", "error_type": type(exc).__name__,
                "eligible_next_48h": 0, "upcoming_next_48h": 0,
                "research_only": True, "no_writes": True}
    snapshot = _snapshot_health(games, instant)
    end = instant + timedelta(hours=48)
    fixtures = [
        g for g in games if g["status"] == "scheduled"
        and not g["postseason"]
        and (stamp := _timestamp(g.get("start_utc"))) is not None
        and instant + timedelta(minutes=PREGAME_BUFFER_MINUTES) < stamp <= end
    ]
    # An open shadow forecast requires the exact same eligible conditions as
    # capture, but the report never records or scores a prediction.
    eligible = candidates(games, now=instant) if snapshot["status"] == "fresh" else []
    return {
        "status": ("ready_for_shadow_capture" if eligible else
                   "source_not_fresh" if snapshot["status"] != "fresh" else
                   "no_eligible_opening_week_fixtures"),
        "snapshot_status": snapshot["status"],
        "snapshot_retrieved_at": snapshot["last_retrieved_at"],
        "upcoming_next_48h": len(fixtures),
        "eligible_next_48h": len(eligible),
        "eligible_samples": [{
            "game_id": r["game_id"], "start_utc": r["start_utc"],
            "home": r["home_team"], "away": r["away_team"],
            "home_previous_season_games": r["prior_home_games"],
            "away_previous_season_games": r["prior_away_games"],
            "home_current_games": r["current_home_games"],
            "away_current_games": r["current_away_games"],
        } for r in eligible[:8]],
        "capture_is_a_separate_write": True,
        "minimum_pregame_minutes": PREGAME_BUFFER_MINUTES,
        "baseline_prediction_unchanged": True,
        "research_only": True, "no_writes": True,
        "not_bookable": True,
    }


def _read_ledger(path, *, max_bytes=10_000_000):
    if not path.is_file():
        return []
    if path.stat().st_size > max_bytes:
        raise ValueError("Cold-start paper ledger exceeds safety limit")
    result = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("Invalid cold-start ledger row")
            expected = item.get("sha256")
            fields = {k: v for k, v in item.items() if k != "sha256"}
            if not isinstance(expected, str) or expected != _signed(fields):
                raise ValueError("Cold-start original hash mismatch")
            result.append(item)
    return result


def audit(home, *, now=None):
    """Fail closed on modified pregame rows, identity clashes or fake finals."""
    instant = _now(now)
    root = Path(home)
    fixture_path = root / "nba_games.jsonl"
    try:
        forecasts = _read_ledger(root / FILENAME)
        settlements = _read_ledger(root / RESULTS)
        games = ({str(g["game_id"]): g for g in read_games(fixture_path)}
                 if fixture_path.is_file() else {})
    except (ValueError, TypeError, OSError, UnicodeError) as exc:
        return {
            "status": "integrity_failed", "research_only": True,
            "method": VERSION, "forecast_count": None,
            "verified_settlements": None, "pending": None,
            "prospective_brier": None,
            "integrity_errors": ["private_ledger_or_verified_fixture_invalid"],
            "error_type": type(exc).__name__,
            "generated_at": instant.isoformat(), "no_writes": True,
            "not_bookable": True, "trusted_v1_changed": False,
            "model_promotion_approved": False, "commercial_use_cleared": False,
        }
    errors = []
    seen, settled = set(), set()
    for row in forecasts:
        gid = str(row.get("game_id"))
        game = games.get(gid)
        captured = _timestamp(row.get("captured_at"))
        tipoff = _timestamp(row.get("start_utc"))
        if gid in seen or not game or not captured or not tipoff:
            errors.append("forecast_id_or_timestamp_invalid")
        elif (captured >= tipoff or row.get("model_version") != VERSION
              or row.get("research_only") is not True
              or row.get("not_bookable") is not True
              or row.get("source") not in APPROVED_RESEARCH_SOURCES
              or any(str(row.get(k)) != str(game.get(k)) for k in
                     ("home_id", "away_id", "date", "season"))
              or _timestamp(game.get("start_utc")) != tipoff
              or not isinstance(row.get("probability_home_win"), (int, float))
              or not 0.25 <= row["probability_home_win"] <= 0.75):
            errors.append("forecast_identity_or_pregame_invalid")
        seen.add(gid)
    for row in settlements:
        gid = str(row.get("game_id"))
        game = games.get(gid)
        verified = _timestamp(row.get("settled_at"))
        tipoff = _timestamp(game.get("start_utc")) if game else None
        if (gid in settled or gid not in seen or not game or
            game["status"] != "final" or not verified or not tipoff or
            verified < tipoff or
            row.get("source") not in APPROVED_RESEARCH_SOURCES or
            row.get("home_score") != game["home_score"] or
            row.get("away_score") != game["away_score"]):
            errors.append("settlement_score_or_provenance_invalid")
        settled.add(gid)
    won = {str(g["game_id"]): int(g["home_score"] > g["away_score"])
           for g in games.values() if g["status"] == "final"}
    done = [r for r in forecasts if str(r["game_id"]) in settled]
    # Only genuinely prospective and verified finals enter paired evaluation.
    # A failed audit withholds every metric rather than exposing a false score.
    scores = []
    for r in done:
        if str(r["game_id"]) in won:
            scores.append({
                "game_id": r["game_id"],
                "actual_home_win": won[str(r["game_id"])],
                "probability_home_win": r["probability_home_win"],
                "previous_season_home_baseline": r["previous_season_home_baseline"],
            })
    paired = _paired_metrics(scores) if not errors else None
    last30 = _paired_metrics(scores[-30:]) if not errors else None
    return {
        "status": "integrity_failed" if errors else (
            "awaiting_first_forecast" if not forecasts else
            "awaiting_first_final" if not done else "forward_observations"),
        "research_only": True, "method": VERSION, "forecast_count": len(forecasts),
        "verified_settlements": len(done), "pending": len(forecasts) - len(done),
        "prospective_brier": paired["candidate_brier"] if paired else None,
        "prospective_baseline_brier": (
            paired["prior_home_baseline_brier"] if paired else None),
        "prospective_paired_brier_improvement": (
            paired["paired_brier_improvement"] if paired else None),
        "prospective_paired_metrics": paired,
        "last_30_verified": last30,
        "integrity_errors": sorted(set(errors)),
        "generated_at": instant.isoformat(), "no_writes": True,
        "not_bookable": True, "trusted_v1_changed": False,
        "model_promotion_approved": False, "commercial_use_cleared": False,
    }


def capture(home, *, now=None):
    instant = _now(now)
    root = Path(home)
    games = read_games(root / "nba_games.jsonl")
    if _snapshot_health(games, instant)["status"] != "fresh":
        return {"status": "source_not_fresh", "created": 0, "research_only": True}
    prior = audit(root, now=instant)
    if prior["status"] == "integrity_failed":
        return {"status": "integrity_failed", "created": 0, "research_only": True}
    seen = {str(row["game_id"]) for row in _read_ledger(root / FILENAME)}
    upcoming = candidates(games, now=instant)
    fresh = [r for r in upcoming if r["game_id"] not in seen][:30]
    if fresh:
        root.mkdir(parents=True, exist_ok=True)
        with (root / FILENAME).open("a", encoding="utf-8") as out:
            for row in fresh:
                value = {**row, "captured_at": instant.isoformat(),
                         "research_only": True, "not_bookable": True,
                         "bookmaker_odds_verified": False}
                out.write(_json({**value, "sha256": _signed(value)}) + "\n")
    return {"status": "research_only", "created": len(fresh),
            "eligible_future": len(upcoming), "already_recorded": len(upcoming) - len(fresh),
            "saved_to_private_only": str(root / FILENAME),
            "not_bookable": True}


def settle(home, *, now=None):
    instant = _now(now)
    root = Path(home)
    prior = audit(root, now=instant)
    if prior["status"] == "integrity_failed":
        return {"status": "integrity_failed", "new_settlements": 0}
    forecasts = _read_ledger(root / FILENAME)
    recorded = {str(row["game_id"]) for row in _read_ledger(root / RESULTS)}
    games_path = root / "nba_games.jsonl"
    games = {str(g["game_id"]): g for g in read_games(games_path)} if games_path.is_file() else {}
    fresh = []
    for forecast in forecasts:
        gid = str(forecast["game_id"])
        game = games.get(gid)
        if (gid in recorded or not game or game["status"] != "final"
            or instant <= _timestamp(game.get("start_utc"))):
            continue
        if game["source"] not in APPROVED_RESEARCH_SOURCES:
            raise ValueError("Unknown NBA verified final source")
        row = {"game_id": gid, "home_score": game["home_score"],
               "away_score": game["away_score"], "source": game["source"],
               "settled_at": instant.isoformat(), "research_only": True}
        fresh.append({**row, "sha256": _signed(row)})
    if fresh:
        with (root / RESULTS).open("a", encoding="utf-8") as out:
            for row in fresh:
                out.write(_json(row) + "\n")
    return {"status": "research_only", "new_settlements": len(fresh),
            "not_bookable": True}


def cycle(home, *, now=None):
    instant = _now(now)
    # Caller must hold the same local lock as main research automation.
    settled = settle(home, now=instant)
    if settled["status"] == "integrity_failed":
        return {"status": "integrity_failed", "created": 0,
                "new_settlements": 0}
    captured = capture(home, now=instant)
    return {**captured, "new_settlements": settled["new_settlements"]}
