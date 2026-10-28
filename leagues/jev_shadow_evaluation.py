"""Independent performance review for Jev shadow decisions, never win forecasting.

Input labels must come from independently verified, settled markets. A Jev
"supported" classification is NOT a calibrated sports probability, so compare
selection quality/coverage, not Jev confidence vs the match outcome.
"""
from __future__ import annotations

from collections import defaultdict
from math import log, isfinite

MIN_HOLDOUT = 300
_ALLOWED = {"supported", "conflicted", "insufficient"}


def _metrics(samples):
    if not samples:
        return {"count": 0, "brier": None, "log_loss": None,
                "win_rate": None}
    n = len(samples)
    wins = sum(y for _, y in samples)
    brier = sum((p - y) ** 2 for p, y in samples) / n
    loss = sum(-(y * log(max(1e-8, p)) + (1 - y) *
                 log(max(1e-8, 1 - p))) for p, y in samples) / n
    return {"count": n, "brier": round(brier, 6),
            "log_loss": round(loss, 6), "win_rate": round(wins / n, 6)}


def review_settled_labels(rows: list[dict], *, min_holdout: int = MIN_HOLDOUT) -> dict:
    """Evaluate on held-out, pregame captured outcomes, not invented scores.

    Each row: fixture_id, market, predicted_probability, verified_outcome 0/1,
    pregame_captured=True, jev_evidence_state, verified_settlement=True.
    Deduplicate by (fixture, market), first write wins; stale or post-kickoff
    labels cannot be silently included. All invalid rows are excluded.
    """
    if type(min_holdout) is not int or min_holdout < MIN_HOLDOUT:
        raise ValueError("minimum held-out sample cannot be weakened")
    retained: list[dict] = []
    seen = set()
    rejected = defaultdict(int)
    for row in rows:
        if not isinstance(row, dict):
            rejected["malformed"] += 1
            continue
        key = (str(row.get("fixture_id") or ""),
               str(row.get("market") or ""))
        category = row.get("jev_evidence_state")
        p = row.get("predicted_probability")
        y = row.get("verified_outcome")
        if (not all(key) or key in seen or category not in _ALLOWED
                or row.get("pregame_captured") is not True
                or row.get("verified_settlement") is not True
                or isinstance(p, bool) or not isinstance(p, (float, int))
                or not isfinite(float(p)) or not 0 < p < 1
                or type(y) is not int or y not in (0, 1)):
            rejected["ineligible_or_duplicate"] += 1
            continue
        seen.add(key)
        retained.append({"market": key[1], "p": float(p), "y": y,
                         "decision": category})
    all_samples = [(r["p"], r["y"]) for r in retained]
    held = [(r["p"], r["y"]) for r in retained
            if r["decision"] == "supported"]
    declined = [(r["p"], r["y"]) for r in retained
                if r["decision"] != "supported"]
    by_market = defaultdict(list)
    for row in retained:
        by_market[row["market"]].append((row["p"], row["y"]))
    total = len(retained)
    return {
        "status": "evaluation_only",
        "total_verified": total,
        "sample_ready": total >= min_holdout and len(held) >= 100,
        "recommendation": "keep_shadow_only",
        "promotion_allowed": False,
        "baseline": _metrics(all_samples),
        "jev_supported": _metrics(held),
        "jev_not_supported": _metrics(declined),
        "supported_coverage": round(len(held) / total, 6) if total else None,
        "false_withhold_wins": sum(r["y"] for r in retained
                                   if r["decision"] != "supported"),
        "by_market": {market: _metrics(values)
                      for market, values in sorted(by_market.items())},
        "rejected": dict(rejected),
        "note": (
            "Outcome labels must be independently verified. Jev classes do "
            "not estimate match win probabilities. No automation promotion "
            "from raw hit rate or a small sample."
        ),
    }
