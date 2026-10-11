"""Read-only market calibration drift diagnostics, never a live selection gate.

Uses first-published, deduplicated settled forecasts. It does not retroactively
change published probabilities, refit a model, or promote a challenger.
"""
from __future__ import annotations

from datetime import date, timedelta
import math


def market_drift_report(observations: list[dict], *, as_of: date | None = None,
                        recent_days: int = 30, baseline_days: int = 60,
                        min_recent: int = 30, min_baseline: int = 20) -> dict:
    """Compare an earlier cohort with a later disjoint settled cohort.

    Dates are taken from the immutable fixture-market identity. Future outcomes
    and duplicate identities cannot leak into the report. Neither cohort is
    allowed to train or change tomorrow's official selections.
    """
    as_of = as_of or date.today()
    recent_start = as_of - timedelta(days=recent_days - 1)
    baseline_start = recent_start - timedelta(days=baseline_days)
    grouped: dict[str, dict[str, list[tuple[float, float]]]] = {}
    seen: set[str] = set()
    excluded = {"invalid_identity": 0, "duplicate": 0,
                "invalid_probability": 0, "outside_window": 0}
    for row in observations:
        identity = str(row.get("identity") or "")
        if identity in seen:
            excluded["duplicate"] += 1
            continue
        seen.add(identity)
        try:
            kickoff_date = date.fromisoformat(identity[:10])
        except ValueError:
            excluded["invalid_identity"] += 1
            continue
        if kickoff_date > as_of or kickoff_date < baseline_start:
            excluded["outside_window"] += 1
            continue
        if not isinstance(row.get("won"), bool):
            excluded["invalid_probability"] += 1
            continue
        try:
            p = float(row.get("probability"))
        except (TypeError, ValueError, OverflowError):
            excluded["invalid_probability"] += 1
            continue
        if not math.isfinite(p) or not 0 < p < 1:
            excluded["invalid_probability"] += 1
            continue
        market = str(row.get("market") or "").strip()
        if not market:
            excluded["invalid_identity"] += 1
            continue
        bucket = "recent" if kickoff_date >= recent_start else "baseline"
        grouped.setdefault(market, {"recent": [], "baseline": []})[bucket].append(
            (p, float(row["won"]))
        )

    def metrics(rows: list[tuple[float, float]]) -> dict:
        n = len(rows)
        return {
            "n": n,
            "predicted": round(sum(p for p, _ in rows) / n, 4) if n else None,
            "actual": round(sum(y for _, y in rows) / n, 4) if n else None,
            "brier": round(sum((p-y)**2 for p, y in rows) / n, 4) if n else None,
        }

    results = {}
    for market, cohorts in sorted(grouped.items()):
        prior = metrics(cohorts["baseline"])
        recent = metrics(cohorts["recent"])
        sufficient = prior["n"] >= min_baseline and recent["n"] >= min_recent
        if sufficient:
            overconfidence = round(recent["predicted"] - recent["actual"], 4)
            change = round(recent["actual"] - prior["actual"], 4)
            flagged = overconfidence >= .08 and change <= -.10
            status = "REVIEW_REQUIRED" if flagged else "OBSERVED_NO_ALERT"
        else:
            overconfidence = None
            change = None
            status = "INSUFFICIENT_EVIDENCE"
        results[market] = {
            "status": status, "baseline": prior, "recent": recent,
            "recent_overconfidence": overconfidence,
            "actual_rate_change": change,
        }
    return {
        "status": "SHADOW_EVIDENCE_ONLY",
        "admission_policy_unchanged": True,
        "automatic_model_promotion": False,
        "as_of": as_of.isoformat(),
        "baseline": {"start": baseline_start.isoformat(),
                     "end": (recent_start - timedelta(days=1)).isoformat()},
        "recent": {"start": recent_start.isoformat(), "end": as_of.isoformat()},
        "minimum_recent": min_recent,
        "minimum_baseline": min_baseline,
        "exclusions": excluded,
        "markets": results,
        "review_markets": sorted(
            key for key, value in results.items()
            if value["status"] == "REVIEW_REQUIRED"
        ),
    }
