"""Independent early NBA advanced experimental forecast ledger.

Append-only and hashed original pregame forecasts + separately verified finals.
Uses the previous-season advanced boxscore research model only. Never inserts
a historical final as a new prospective sample and never replaces the v1
moneyline, v1 score, official BetSightly or bookmaker ledgers.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from basketball.research_coldstart import _now, _json, _signed, _read_ledger
from basketball.research_data import read_games, APPROVED_RESEARCH_SOURCES
from basketball.research_readiness import _snapshot_health, _timestamp
from basketball.research_opening_score import (
    FORECASTS as REFERENCE, VERSION as REFERENCE_VERSION,
    PREGAME_BUFFER, TARGETS,
)
from basketball.research_early_advanced import (
    VERSION, _box_snapshot, projections,
)

FORECASTS = "early_advanced_forecasts.jsonl"
FINALS = "early_advanced_settlements.jsonl"


def _finite(value):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value))


def _paired_statistics(forecasts, final_rows):
    outcomes = {str(r["game_id"]): r for r in final_rows}
    matched = []
    for row in forecasts:
        finished = outcomes.get(str(row["game_id"]))
        if finished is None:
            continue
        home = finished["home_score"]
        away = finished["away_score"]
        matched.append({
            **row, "actual_total": home+away,
            "actual_home_margin": home-away,
            "actual_home_points": home,
            "actual_away_points": away,
        })
    result = {"games": len(matched), "targets": {}}
    for name, predicted, _, actual in TARGETS:
        n = len(matched)
        if not n:
            result["targets"][name] = {
                "advanced_mae": None, "original_score_mae": None,
                "paired_improvement": None, "advanced_bias": None,
            }
            continue
        advanced = [x[predicted]-x[actual] for x in matched]
        reference = [x["original_"+predicted]-x[actual]
                     for x in matched]
        result["targets"][name] = {
            "advanced_mae": round(sum(abs(v) for v in advanced)/n, 4),
            "original_score_mae": round(
                sum(abs(v) for v in reference)/n, 4),
            "paired_improvement": round(
                sum(abs(v) - abs(a) for v,a in zip(reference,advanced))/n, 4),
            "advanced_bias": round(sum(advanced)/n, 4),
        }
    return result


def audit(home, *, now=None):
    """Fail closed on changed hashes, identities, timestamps and fake finals."""
    root = Path(home)
    instant = _now(now)
    try:
        forecasts = _read_ledger(root / FORECASTS)
        settlements = _read_ledger(root / FINALS)
        reference = _read_ledger(root / REFERENCE)
        path = root / "nba_games.jsonl"
        games = {str(g["game_id"]): g for g in read_games(path)} if (
            path.is_file()) else {}
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        return {
            "status": "integrity_failed", "reason": type(exc).__name__,
            "forecast_count": None, "settled": None, "pending": None,
            "paired_forward_metrics": None, "research_only": True,
            "no_writes": True,
        }
    ref_map = {}
    seen = set()
    errors = []
    for row in reference:
        gid = str(row.get("game_id"))
        if gid in ref_map:
            errors.append("duplicate_reference_forecast")
        ref_map[gid] = row
    for row in forecasts:
        gid = str(row.get("game_id"))
        game = games.get(gid)
        original = ref_map.get(gid)
        captured = _timestamp(row.get("captured_at"))
        kickoff = _timestamp(row.get("start_utc"))
        numeric = [row.get(k) for k in (
            "predicted_total", "predicted_home_margin",
            "predicted_home_points", "predicted_away_points",
            "estimated_possessions", "original_predicted_total",
            "original_predicted_home_margin",
            "original_predicted_home_points",
            "original_predicted_away_points")]
        if (gid in seen or not game or not original or
            row.get("model_version") != VERSION or
            row.get("reference_model") != REFERENCE_VERSION or
            row.get("research_only") is not True or
            row.get("not_bookable") is not True or
            row.get("bookmaker_prices_verified") is not False or
            row.get("source") not in APPROVED_RESEARCH_SOURCES or
            not captured or not kickoff or
            captured + PREGAME_BUFFER >= kickoff or
            _timestamp(game.get("start_utc")) != kickoff or
            _timestamp(original.get("start_utc")) != kickoff or
            _timestamp(original.get("captured_at")) is None or
            _timestamp(original["captured_at"]) + PREGAME_BUFFER >= kickoff or
            any(str(row.get(k)) != str(game.get(k))
                for k in ("date", "season", "home_id", "away_id")) or
            any(str(row.get(k)) != str(original.get(k))
                for k in ("date", "season", "home_id", "away_id")) or
            any(not _finite(v) for v in numeric) or
            abs(row["predicted_home_points"] +
                row["predicted_away_points"] -
                row["predicted_total"]) > 0.0002 or
            abs(row["predicted_home_points"] -
                row["predicted_away_points"] -
                row["predicted_home_margin"]) > 0.0002 or
            any(row.get("original_"+k) != original.get(k)
                for k in ("predicted_total", "predicted_home_margin",
                          "predicted_home_points", "predicted_away_points"))):
            errors.append("invalid_pregame_advanced_forecast")
        seen.add(gid)
    verified = {}
    for row in settlements:
        gid = str(row.get("game_id"))
        game = games.get(gid)
        final_at = _timestamp(row.get("settled_at"))
        if (gid in verified or gid not in seen or game is None or
            game["status"] != "final" or
            row.get("source") not in APPROVED_RESEARCH_SOURCES or
            row.get("source") != game.get("source") or
            not final_at or
            final_at <= _timestamp(game.get("start_utc")) or
            row.get("home_score") != game.get("home_score") or
            row.get("away_score") != game.get("away_score") or
            row.get("research_only") is not True):
            errors.append("invalid_verified_advanced_settlement")
        verified[gid] = row
    if errors:
        return {
            "status": "integrity_failed",
            "integrity_errors": sorted(set(errors)),
            "forecast_count": len(forecasts), "settled": len(verified),
            "pending": None, "paired_forward_metrics": None,
            "research_only": True, "no_writes": True,
        }
    pending = Counter()
    for row in forecasts:
        gid = str(row["game_id"])
        g = games[gid]
        start = _timestamp(row["start_utc"])
        if gid in verified:
            pending["verified_settled"] += 1
        elif g["status"] == "final":
            pending["final_available_pending_grade"] += 1
        elif instant < start:
            pending["not_started"] += 1
        elif instant > start + timedelta(hours=4):
            pending["overdue_unverified_final"] += 1
        else:
            pending["awaiting_final"] += 1
    result = _paired_statistics(forecasts, list(verified.values()))
    return {
        "status": ("awaiting_first_forecast" if not forecasts else
                   "awaiting_first_verified_final" if not verified else
                   "forward_observations"),
        "model_version": VERSION,
        "forecast_count": len(forecasts),
        "settled": len(verified),
        "pending": len(forecasts)-len(verified),
        "operational_states": dict(sorted(pending.items())),
        "paired_forward_metrics": result,
        "integrity_errors": [],
        "reference_score_forecast_count": len(reference),
        "source_verified_only": True, "research_only": True,
        "not_bookable": True, "no_writes": True,
        "model_promoted": False, "football_production_unchanged": True,
    }


def capture(home, *, now=None):
    """Only save still-future research comparisons with signed original v1."""
    root = Path(home)
    instant = _now(now)
    checked = audit(root, now=instant)
    if checked["status"] == "integrity_failed":
        return {"status": "integrity_failed", "created": 0}
    games = read_games(root / "nba_games.jsonl")
    if _snapshot_health(games, instant)["status"] != "fresh":
        return {"status": "source_not_fresh", "created": 0}
    reference = {str(r["game_id"]): r for r in
                 _read_ledger(root / REFERENCE)}
    paired_game_ids = {str(r["game_id"]) for r in
                       _read_ledger(root / FORECASTS)}
    cleaned, boxes, _ = _box_snapshot(root)
    candidates, _ = projections(cleaned, boxes, now=instant)
    fresh = []
    for p in candidates:
        gid = str(p["game_id"])
        orig = reference.get(gid)
        if gid in paired_game_ids or not orig:
            continue
        kickoff = _timestamp(p["start_utc"])
        if (kickoff is None or instant + PREGAME_BUFFER >= kickoff or
            _timestamp(orig.get("start_utc")) != kickoff or
            any(str(p.get(k)) != str(orig.get(k))
                for k in ("date", "season", "home_id", "away_id"))):
            continue
        row = {k: v for k,v in p.items()
               if k not in ("actual_total", "actual_home_margin",
                            "actual_home_points", "actual_away_points")}
        # Genuine paired forward evaluation uses the original signed
        # before-tipoff reference, never a retroactively recalculated
        # 'reference' baseline with knowledge of later finals.
        for name in ("predicted_total", "predicted_home_margin",
                     "predicted_home_points", "predicted_away_points"):
            row["original_"+name] = orig[name]
        row.update({
            "captured_at": instant.isoformat(),
            "research_only": True, "not_bookable": True,
            "bookmaker_prices_verified": False,
        })
        fresh.append({**row, "sha256": _signed(row)})
    if fresh:
        with (root / FORECASTS).open("a", encoding="utf-8") as handle:
            for record in fresh[:30]:
                handle.write(_json(record)+"\n")
    return {
        "status": "research_only",
        "created": min(len(fresh),30),
        "eligible_with_past_advanced_and_original": len(fresh),
        "reference_forecast_count": len(reference),
        "not_bookable": True,
    }


def settle(home, *, now=None):
    """Verified final scores only, no outcome guess or delayed-as-loss."""
    root = Path(home)
    instant = _now(now)
    verified = audit(root, now=instant)
    if verified["status"] == "integrity_failed":
        return {"status": "integrity_failed", "new_settlements": 0}
    saved = _read_ledger(root / FORECASTS)
    previous = {str(row["game_id"]) for row in
                _read_ledger(root / FINALS)}
    path = root / "nba_games.jsonl"
    games = {str(g["game_id"]): g for g in read_games(path)} if (
        path.is_file()) else {}
    new = []
    for row in saved:
        gid = str(row["game_id"])
        fixture = games.get(gid)
        kickoff = _timestamp(row["start_utc"])
        if (gid in previous or fixture is None or
            fixture["status"] != "final" or
            kickoff is None or instant <= kickoff or
            fixture["source"] not in APPROVED_RESEARCH_SOURCES):
            continue
        result = {
            "game_id": gid, "home_score": fixture["home_score"],
            "away_score": fixture["away_score"],
            "source": fixture["source"],
            "settled_at": instant.isoformat(), "research_only": True,
        }
        new.append({**result, "sha256": _signed(result)})
    if new:
        with (root / FINALS).open("a", encoding="utf-8") as handle:
            for result in new:
                handle.write(_json(result)+"\n")
    return {"status": "research_only", "new_settlements": len(new),
            "not_bookable": True}


def cycle(home, *, now=None):
    instant = _now(now)
    scored = settle(home, now=instant)
    if scored["status"] == "integrity_failed":
        return {"status": "integrity_failed", "created": 0,
                "new_settlements": 0}
    forecast = capture(home, now=instant)
    return {**forecast, "new_settlements": scored["new_settlements"]}
