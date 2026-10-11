"""Offline paired challenger evaluation, never a live promotion decision.

Input observations must be independently settled with both probabilities
captured before kickoff. All comparisons use the same fixture/market trials.
No historic data, bookmaker price or settlement is silently generated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math

MIN_MARKET_SAMPLES = 100
MIN_DISTINCT_DAYS = 7


def _instant(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps require a timezone")
    return dt.astimezone(timezone.utc)


def evaluate_paired(rows: list[dict], *, evaluation_start: str) -> dict:
    """Holdout begins on evaluation_start; reject leakage and duplicates.

    Each row: fixture_id, market, observed_at, kickoff, settled_at,
    outcome (0/1), champion_probability, challenger_probability.
    These inputs need verifiable rights and upstream provenance.
    """
    cutoff = _instant(evaluation_start)
    seen = set()
    by_market = defaultdict(list)
    dropped_before_cutoff = 0
    for row in rows:
        kickoff = _instant(row["kickoff"])
        if kickoff < cutoff:
            dropped_before_cutoff += 1
            continue
        observed = _instant(row["observed_at"])
        settled = _instant(row["settled_at"])
        if observed >= kickoff or settled <= kickoff:
            raise ValueError("invalid forecast or settlement chronology")
        key = (str(row["fixture_id"]), str(row["market"]))
        if not all(key):
            raise ValueError("fixture and market required")
        if key in seen:
            raise ValueError("duplicate fixture and market")
        seen.add(key)
        if type(row["outcome"]) is not int or row["outcome"] not in (0, 1):
            raise ValueError("outcome must be an independently settled binary label")
        probs = []
        for name in ("champion_probability", "challenger_probability"):
            value = float(row[name])
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError("probabilities must be finite and strictly between 0 and 1")
            probs.append(value)
        by_market[key[1]].append((kickoff.date().isoformat(), row["outcome"], *probs))

    market_reports = {}
    for market, items in sorted(by_market.items()):
        n = len(items)
        days = len({item[0] for item in items})
        champion_brier = sum((c - y) ** 2 for _, y, c, _ in items) / n
        challenger_brier = sum((p - y) ** 2 for _, y, _, p in items) / n
        market_reports[market] = {
            "settled": n,
            "distinct_kickoff_days_utc": days,
            "champion_brier": round(champion_brier, 6),
            "challenger_brier": round(challenger_brier, 6),
            "brier_improvement": round(champion_brier - challenger_brier, 6),
            "evidence": "REVIEW_READY" if n >= MIN_MARKET_SAMPLES and days >= MIN_DISTINCT_DAYS else "INSUFFICIENT",
        }
    return {
        "mode": "OFFLINE_SHADOW_ONLY",
        "evaluation_start_utc": cutoff.isoformat(),
        "excluded_pre_holdout": dropped_before_cutoff,
        "paired_market_count": len(by_market),
        "markets": market_reports,
        "automatic_model_promotion": False,
        "claim_of_positive_roi_or_clv": False,
        "data_provenance_and_rights_verified_by_this_function": False,
    }
