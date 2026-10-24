"""Read-only prospective NBA paper-model evaluation.

Only forecasts saved before tipoff AND independently settled after tipoff
enter the prospective cohort. No historical backtest games are imported here.
Requires neither sportsbook odds nor a public deployment.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from basketball.research_store import _utc

BUCKET_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
MIN_REVIEW_GAMES = 100
BASELINE_HOME_PROB = 0.5


def _interval(wins: int, total: int) -> dict | None:
    """Wilson score interval, two-sided 95%, descriptive rather than a test."""
    if not total:
        return None
    z = 1.95996398454
    p = wins / total
    divisor = 1 + z*z/total
    center = (p + z*z/(2*total)) / divisor
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / divisor
    return {"lower": round(max(0, center-half), 4),
            "upper": round(min(1, center+half), 4),
            "method": "Wilson 95% descriptive interval"}


def _prob_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "accuracy": None, "accuracy_95pct_ci": None,
                "brier": None, "log_loss": None, "baseline_brier": None,
                "brier_skill_vs_50_50": None}
    n = len(rows)
    wins = sum((r["p"] >= 0.5) == bool(r["y"]) for r in rows)
    brier = sum((r["p"]-r["y"])**2 for r in rows)/n
    eps = 1e-12
    loss = -sum(
        r["y"]*math.log(max(eps, min(1-eps, r["p"]))) +
        (1-r["y"])*math.log(max(eps, min(1-eps, 1-r["p"])))
        for r in rows
    )/n
    baseline_brier = 0.25
    return {
        "count": n, "accuracy": round(wins/n, 5),
        "correct": wins, "accuracy_95pct_ci": _interval(wins, n),
        "brier": round(brier, 5), "log_loss": round(loss, 5),
        "baseline_brier": baseline_brier,
        "brier_skill_vs_50_50": round(1-brier/baseline_brier, 5),
        "baseline_definition": "constant 0.50 home-win probability",
    }


def _calibration(rows: list[dict]) -> dict:
    bins = []
    weighted_error = 0.0
    for i in range(len(BUCKET_EDGES)-1):
        lo, hi = BUCKET_EDGES[i:i+2]
        sample = [
            r for r in rows if
            (lo <= r["p"] < hi or
             (i == len(BUCKET_EDGES)-2 and r["p"] == hi))
        ]
        n = len(sample)
        avg_p = sum(r["p"] for r in sample)/n if n else None
        obs = sum(r["y"] for r in sample)/n if n else None
        if n:
            weighted_error += n/len(rows) * abs(avg_p-obs)
        bins.append({
            "lower": lo, "upper": hi,
            "count": n,
            "average_forecast": round(avg_p, 5) if n else None,
            "observed_home_win": round(obs, 5) if n else None,
            "descriptive_only": n < 20,
        })
    return {
        "bins": bins,
        "ece": round(weighted_error, 5) if len(rows) >= MIN_REVIEW_GAMES
        else None,
        "ece_minimum_settled_games": MIN_REVIEW_GAMES,
        "ece_note": "Fixed five-bin ECE; omitted until at least 100 settlements",
    }


def _score_errors(rows: list[dict]) -> dict:
    projections = [r for r in rows
                   if r["predicted_total"] is not None
                   and r["predicted_margin"] is not None]
    if not projections:
        return {"count": 0, "total_points_mae": None,
                "home_margin_mae": None, "total_points_bias": None,
                "home_margin_bias": None}
    n = len(projections)
    t = [
        r["predicted_total"]-r["home_score"]-r["away_score"]
        for r in projections
    ]
    m = [
        r["predicted_margin"]-(r["home_score"]-r["away_score"])
        for r in projections
    ]
    return {
        "count": n, "total_points_mae": round(sum(map(abs,t))/n, 4),
        "home_margin_mae": round(sum(map(abs,m))/n, 4),
        "total_points_bias": round(sum(t)/n, 4),
        "home_margin_bias": round(sum(m)/n, 4),
    }


def _read_cohort(connection: sqlite3.Connection) -> tuple[list[dict], list[str]]:
    rows = connection.execute("""
        SELECT f.game_id, f.fixture_date, f.start_utc, f.created_at,
               f.inserted_at, f.home_team, f.away_team, f.model_version,
               f.home_win_probability, f.expected_total_points,
               f.expected_home_margin, f.raw_json, f.sha256,
               s.home_score, s.away_score, s.home_won, s.recorded_at, s.source
          FROM forecasts f LEFT JOIN settlements s ON s.game_id=f.game_id
         ORDER BY f.start_utc, f.game_id
    """).fetchall()
    errors = []
    parsed = []
    for raw in rows:
        r = dict(raw)
        ident = r["game_id"]
        try:
            content = r["raw_json"]
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest != r["sha256"]:
                raise ValueError("raw payload SHA256 mismatch")
            created = _utc(r["created_at"])
            inserted = _utc(r["inserted_at"])
            tipoff = _utc(r["start_utc"])
            if created >= tipoff or inserted >= tipoff:
                raise ValueError("record created or inserted after tipoff")
            if created > inserted:
                raise ValueError("forecast created after insertion")
            if not math.isfinite(float(r["home_win_probability"])) or not (
                    0 <= float(r["home_win_probability"]) <= 1):
                raise ValueError("invalid probability")
            if r["recorded_at"] is not None:
                settled_at = _utc(r["recorded_at"])
                if settled_at <= tipoff:
                    raise ValueError("settlement recorded before tipoff")
                if (not isinstance(r["home_score"], int) or
                        not isinstance(r["away_score"], int) or
                        r["home_score"] == r["away_score"]):
                    raise ValueError("invalid NBA final score")
                if int(r["home_score"] > r["away_score"]) != r["home_won"]:
                    raise ValueError("inconsistent outcome against verified score")
                if not r["source"]:
                    raise ValueError("missing score provenance")
            r["p"] = float(r["home_win_probability"])
            r["y"] = r["home_won"]
            r["predicted_total"] = r["expected_total_points"]
            r["predicted_margin"] = r["expected_home_margin"]
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            errors.append(f"{ident}: {str(exc)[:90]}")
            continue
        parsed.append(r)
    return parsed, errors


def prospective_report(db_path: str | Path) -> dict:
    """Read-only evaluation; never create SQLite DB, touch models or recompute picks."""
    path = Path(db_path)
    if not path.is_file():
        return {
            "status": "awaiting_first_forecast", "forecast_count": 0,
            "settled_count": 0, "pending_count": 0,
            "research_only": True, "no_writes": True,
            "bookmaker_odds_verified": False, "betting_roi": None,
        }
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        # Never call open_ledger; that performs DDL and schema upgrades.
        rows, errors = _read_cohort(db)
    if errors:
        return {
            "status": "integrity_failed", "issues": errors[:25],
            "issue_count": len(errors),
            "metrics_withheld": True,
            "research_only": True, "no_writes": True,
            "bookmaker_odds_verified": False, "betting_roi": None,
        }
    settled = [r for r in rows if r["recorded_at"] is not None]
    pending = [r for r in rows if r["recorded_at"] is None]
    version_cohorts = defaultdict(list)
    for row in settled:
        version_cohorts[row["model_version"]].append(row)
    n = len(settled)
    overall = _prob_metrics(settled)
    ready = n >= MIN_REVIEW_GAMES
    return {
        "status": ("awaiting_first_forecast" if not rows
                   else "awaiting_verified_final" if n == 0
                   else "descriptive_only" if not ready
                   else "review_ready"),
        "phase": "prospective_paper_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "forecast_count": len(rows), "settled_count": n,
        "pending_count": len(pending),
        "first_forecast_at": min((r["created_at"] for r in rows),default=None),
        "last_forecast_at": max((r["created_at"] for r in rows),default=None),
        "review_minimum_settled": MIN_REVIEW_GAMES,
        "sample_size_gate_met": ready,
        "limitations": (
            "Observational paper sample; no randomization, causal evidence, "
            "market odds, verified betting ROI or profitability claim. "
            "100-game threshold is a review checkpoint, not proof of quality."
        ),
        "overall": overall,
        "calibration": _calibration(settled),
        "score_projection_errors": _score_errors(settled),
        "rolling_settled": {
            "last_30": _prob_metrics(settled[-30:]),
            "last_100": _prob_metrics(settled[-100:]),
        },
        "by_model_version": {
            version: _prob_metrics(group)
            for version, group in sorted(version_cohorts.items())
        },
        "pending_fixtures": [
            {"game_id": r["game_id"], "fixture_date": r["fixture_date"],
             "start_utc": r["start_utc"],
             "home_team": r["home_team"], "away_team": r["away_team"]}
            for r in pending[:20]
        ],
        "integrity": {"sha256_records_verified": len(rows), "issues": 0},
        "research_only": True, "no_writes": True,
        "bookmaker_odds_verified": False, "betting_roi": None,
        "public_publishing_enabled": False,
    }
