"""Read-only, fail-closed 2027 NBA shadow/model/market audit.

This is research, not betting. No model training, data writes or publishing.
Only saved-before-tipoff predictions and exact verified NBA finals are scored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MODEL = "nba-advanced-shadow-2026-v1"
MIN_REVIEW = 100
LINES = {"total_points": (220.5, 225.5, 230.5),
         "home_margin": (-5.5, -2.5, 2.5, 5.5),
         "home_team_points": (107.5, 112.5, 117.5),
         "away_team_points": (107.5, 112.5, 117.5)}
SOURCES = {"sportsdataverse:espn_nba_schedules:v1",
           "espn:nba:scoreboard:v1", "nba:official_live_cdn:scoreboard:v1",
           "balldontlie:nba:v1"}


def _time(value):
    if not isinstance(value, str):
        raise ValueError("missing_timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("naive_timestamp")
    return result.astimezone(timezone.utc)


def _numeric(value, probability=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_numeric_value")
    result = float(value)
    if not math.isfinite(result) or (probability and not 0 <= result <= 1):
        raise ValueError("invalid_probability")
    return result


def _read_json(path, empty):
    if not path.is_file():
        return empty
    if path.stat().st_size > 25_000_000:
        raise ValueError("oversized_research_file")
    return json.loads(path.read_text(encoding="utf-8"))


def _forecast_rows(path):
    if not path.is_file():
        return []
    if path.stat().st_size > 25_000_000:
        raise ValueError("oversized_forecast_ledger")
    seen, rows = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("nonobject_forecast")
        gid = str(row.get("game_id", ""))
        if not gid or gid in seen:
            raise ValueError("duplicate_or_empty_forecast_identity")
        seen.add(gid)
        raw = {k: v for k, v in row.items() if k not in ("sha256", "settlement")}
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != row.get("sha256"):
            raise ValueError("forecast_sha256_integrity_mismatch")
        if (row.get("season") != 2027 or row.get("model_version") != MODEL
                or row.get("research_only") is not True
                or row.get("not_for_betting") is not True
                or row.get("bookmaker_odds_verified") is not False
                or row.get("booking_code") is not None
                or row.get("settlement") is not None):
            raise ValueError("forecast_policy_or_model_mismatch")
        if _time(row.get("created_at")) >= _time(row.get("start_utc")):
            raise ValueError("forecast_not_before_tipoff")
        if (not str(row.get("home_id", "")) or not str(row.get("away_id", ""))
                or str(row["home_id"]) == str(row["away_id"])):
            raise ValueError("invalid_team_identity")
        for key in ("candidate_home_win_probability", "matched_v1_home_win_probability"):
            _numeric(row.get(key), True)
        for key in ("candidate_total_points", "candidate_home_margin",
                    "matched_v1_total_points", "matched_v1_home_margin"):
            if row.get(key) is not None:
                _numeric(row[key])
        grid = row.get("market_probabilities")
        if grid is not None:
            if not isinstance(grid, dict):
                raise ValueError("invalid_market_grid")
            if grid.get("status") == "research_only":
                if (grid.get("thresholds_source") !=
                        "fixed illustrative research grid, not sportsbook"
                        or grid.get("no_bookmaker_odds") is not True):
                    raise ValueError("bookmaker_market_policy_conflict")
                markets = grid.get("markets") or {}
                if not isinstance(markets, dict):
                    raise ValueError("invalid_market_families")
                for target, entries in markets.items():
                    if target not in LINES or not isinstance(entries, list):
                        raise ValueError("unsupported_market")
                    if any(not isinstance(entry, dict) for entry in entries):
                        raise ValueError("malformed_market")
                    if tuple(_numeric(entry.get("line")) for entry in entries) != LINES[target]:
                        raise ValueError("modified_research_thresholds")
                    for entry in entries:
                        mass = sum(_numeric(entry.get(k), True) for k in (
                            "above_probability", "below_probability", "push_probability"))
                        if abs(mass-1) > 0.00001:
                            raise ValueError("market_probability_mass_conflict")
            elif grid.get("status") != "blocked":
                raise ValueError("unrecognized_market_grid")
        rows.append(row)
    return rows


def _final_rows(path):
    if not path.is_file():
        return {}
    if path.stat().st_size > 25_000_000:
        raise ValueError("oversized_fixture_snapshot")
    finals = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        game = json.loads(line)
        if game.get("season") != 2027 or game.get("status") != "final":
            continue
        gid = str(game.get("game_id", ""))
        if not gid or gid in finals:
            raise ValueError("duplicate_final_fixture")
        finals[gid] = game
    return finals


def _paired(rows):
    if not rows:
        return {"games": 0, "candidate_brier": None, "matched_v1_brier": None,
                "paired_brier_improvement": None}
    n = len(rows)
    def metric(field):
        values = [(row[field], y) for row, y in rows]
        brier = sum((p-y)**2 for p, y in values)/n
        accuracy = sum(int((p>=.5)==bool(y)) for p, y in values)/n
        log_loss = -sum(
            y*math.log(max(1e-12, min(1-1e-12, p))) +
            (1-y)*math.log(max(1e-12, min(1-1e-12, 1-p)))
            for p, y in values)/n
        return brier, accuracy, log_loss
    cb, ca, cl = metric("candidate_home_win_probability")
    bb, ba, bl = metric("matched_v1_home_win_probability")
    return {"games": n, "candidate_brier": round(cb, 6),
            "matched_v1_brier": round(bb, 6),
            "paired_brier_improvement": round(bb-cb, 6),
            "candidate_accuracy": round(ca, 5),
            "matched_v1_accuracy": round(ba, 5),
            "candidate_log_loss": round(cl, 6),
            "matched_v1_log_loss": round(bl, 6)}


def _score_errors(rows):
    result = {}
    for model in ("candidate", "matched_v1"):
        for target in ("total_points", "home_margin"):
            errors = []
            for row, h, a in rows:
                estimate = row.get(f"{model}_{target}")
                if estimate is not None:
                    actual = h+a if target == "total_points" else h-a
                    errors.append(estimate-actual)
            result[f"{model}_{target}"] = {
                "games": len(errors),
                "mae": round(sum(map(abs, errors))/len(errors), 5) if errors else None,
                "bias": round(sum(errors)/len(errors), 5) if errors else None}
    return result


def _market_metrics(rows):
    buckets, pushes, no_mass = defaultdict(list), defaultdict(int), defaultdict(int)
    for row, h, a in rows:
        grid = row.get("market_probabilities") or {}
        if grid.get("status") != "research_only":
            continue
        scores = {"total_points": h+a, "home_margin": h-a,
                  "home_team_points": h, "away_team_points": a}
        for target, entries in (grid.get("markets") or {}).items():
            for entry in entries:
                key = (target, float(entry["line"]))
                if scores[target] == key[1]:
                    pushes[key] += 1
                    continue
                above, below = entry["above_probability"], entry["below_probability"]
                if above+below < 1e-12:
                    no_mass[key] += 1
                    continue
                # Correct for historical push mass before scoring nonpush games.
                conditional = above/(above+below)
                buckets[key].append((conditional, int(scores[target] > key[1])))
    result = []
    for target, lines in LINES.items():
        for line in lines:
            key = (target, line)
            sample = buckets[key]
            n = len(sample)
            result.append({"target": target, "line": line,
                           "nonpush_scored": n,
                           "actual_pushes": pushes[key],
                           "unscorable_zero_nonpush_mass": no_mass[key],
                           "conditional_nonpush_brier": (
                               round(sum((p-y)**2 for p,y in sample)/n, 6)
                               if n else None),
                           "review_checkpoint_met": n >= MIN_REVIEW})
    return {"metrics": result, "scoring_rule": "Brier p(above | not push)",
            "bookmaker_lines": False, "betting_roi": None}


def wave2_report(home: str | Path, *, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware clock required")
    now = now.astimezone(timezone.utc)
    root = Path(home)
    base = {"phase": "wave2_private_advanced_forward_evaluation",
            "generated_at": now.isoformat(), "research_only": True,
            "local_only": True, "no_writes": True,
            "public_publishing_enabled": False,
            "bookmaker_odds_verified": False, "betting_roi": None,
            "model_promotion_approved": False,
            "review_checkpoint": MIN_REVIEW}
    try:
        forecasts = _forecast_rows(root/"advanced"/"shadow_2027.jsonl")
        settlements = _read_json(root/"advanced"/"shadow_settlements_2027.json", {})
        if not isinstance(settlements, dict):
            raise ValueError("malformed_settlements")
        by_id = {str(row["game_id"]): row for row in forecasts}
        if set(settlements)-set(by_id):
            raise ValueError("orphan_settlement_identity")
        finals = _final_rows(root/"nba_games.jsonl")
        scored, pending = [], []
        for row in forecasts:
            if _time(row["created_at"]) > now:
                raise ValueError("future_dated_forecast")
            gid = str(row["game_id"])
            if gid not in settlements:
                pending.append(gid)
                continue
            settlement = settlements[gid]
            if not isinstance(settlement, dict):
                raise ValueError("malformed_settlement")
            game = finals.get(gid)
            if game is None:
                raise ValueError("settlement_without_verified_final")
            scores = settlement.get("scores")
            if (not isinstance(scores, list) or len(scores) != 2
                    or any(isinstance(x,bool) or not isinstance(x,int)
                           or x < 0 or x > 300 for x in scores)
                    or scores[0] == scores[1]):
                raise ValueError("invalid_final_scores")
            if (_time(settlement.get("verified_at")) <= _time(row["start_utc"])
                    or _time(settlement.get("verified_at")) > now
                    or settlement.get("source") not in SOURCES
                    or game.get("source") not in SOURCES):
                raise ValueError("unverified_settlement_provenance")
            if (str(game.get("home_id")) != str(row["home_id"])
                    or str(game.get("away_id")) != str(row["away_id"])
                    or game.get("date") != row.get("fixture_date")
                    or _time(game.get("start_utc")) != _time(row["start_utc"])
                    or game.get("home_score") != scores[0]
                    or game.get("away_score") != scores[1]
                    or game.get("postseason") is True):
                raise ValueError("verified_fixture_result_mismatch")
            scored.append((row, scores[0], scores[1]))
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        return {**base, "status": "integrity_failed", "metrics_withheld": True,
                "reason": str(exc)[:110], "settled_count": None}
    scored.sort(key=lambda x: (_time(x[0]["start_utc"]), str(x[0]["game_id"])))
    paired = [(row, int(h > a)) for row, h, a in scored]
    calibration = []
    for i in range(5):
        low, high = i/5, (i+1)/5
        sample = [(row["candidate_home_win_probability"], y)
                  for row,y in paired
                  if low <= row["candidate_home_win_probability"] < high
                  or (i == 4 and row["candidate_home_win_probability"] == 1)]
        n = len(sample)
        calibration.append({
            "lower": low, "upper": high, "games": n,
            "average_probability": round(sum(p for p,_ in sample)/n,5) if n else None,
            "observed_home_win": round(sum(y for _,y in sample)/n,5) if n else None,
            "small_sample": n < 20})
    return {**base,
            "status": ("awaiting_first_forecast" if not forecasts else
                       "awaiting_verified_finals" if not scored else
                       "forward_review_checkpoint" if len(scored) >= MIN_REVIEW
                       else "descriptive_only"),
            "metrics_withheld": False,
            "forecast_count": len(forecasts),
            "settled_count": len(scored), "pending_count": len(pending),
            "pending_game_ids_sample": pending[:10],
            "integrity": {"original_hashes_checked": len(forecasts),
                          "verified_finals_checked": len(scored), "errors": 0},
            "paired_moneyline": _paired(paired),
            "last_30_settled": _paired(paired[-30:]),
            "candidate_calibration": calibration,
            "point_projection_errors": _score_errors(scored),
            "market_evaluation": _market_metrics(scored),
            "limitations": (
                "Matched-v1 is same-cohort reduced-feature comparator, not deployed v1. "
                "2026 validation was used for tuning, not untouched. "
                "100 forward finals is descriptive only, not evidence of a betting edge.")}


def main(argv=None):
    p = argparse.ArgumentParser(description="Private NBA Wave 2 evaluation")
    p.add_argument("--home", type=Path,
                   default=Path("data/basketball/research"))
    report = wave2_report(p.parse_args(argv).home)
    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "integrity_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
