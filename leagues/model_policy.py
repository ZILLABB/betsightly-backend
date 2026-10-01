"""Offline, market-specific champion/challenger evaluation.

This module never changes inference or promotes a model. It only evaluates
prospectively recorded, settled observations with explicit out-of-sample
provenance. Historical training overlap or missing lineage fails closed.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from leagues.market_registry import MARKETS

POLICY_VERSION = "market-model-policy-v1"
CHAMPION_VERSION = "current-market-poisson-v1"
FAMILIES = ("xgboost", "lightgbm", "catboost", "neural")
MIN_OOS_OBSERVATIONS = 300  # provisional review threshold, not a promotion trigger


def market_policy(market: str) -> dict:
    spec = MARKETS[market]
    challengers = list(FAMILIES) + ["ml_blend"] if spec.ml_support != "NONE" else []
    return {
        "market": market, "policy_version": POLICY_VERSION,
        "activation": spec.activation,
        "champion": "base_model", "champion_version": CHAMPION_VERSION,
        "fallback": "base_model", "challengers": challengers,
        "evaluation_sample": 0, "last_evaluated_at": None,
        "promotion_status": ("NOT_EVALUATED" if spec.activation == "ACTIVE"
                             else "SHADOW_ONLY"),
        "reason": ("No verified out-of-sample comparison has approved a replacement."
                   if spec.activation == "ACTIVE" else
                   "This market is not activated for public selection."),
    }


def _metrics(rows: list[tuple[float, int, dict]]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    brier = sum((p - y) ** 2 for p, y, _ in rows) / n
    log_loss = -sum(y * math.log(max(1e-9, p)) +
                    (1 - y) * math.log(max(1e-9, 1 - p))
                    for p, y, _ in rows) / n
    bands = defaultdict(list)
    for p, y, row in rows:
        bands[min(9, int(p * 10))].append((p, y))
    ece = sum(len(cell) / n * abs(
        sum(p for p, _ in cell) / len(cell) -
        sum(y for _, y in cell) / len(cell))
        for cell in bands.values())
    by_league = defaultdict(list)
    for p, y, row in rows:
        if row.get("league"):
            by_league[str(row["league"])].append((p, y))
    quoted = []
    bookmaker = []
    for p, y, row in rows:
        try:
            price = float(row["sportybet_odds"])
            if row.get("immutable_price") is True and math.isfinite(price) and price > 1:
                quoted.append((p, y, price))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            implied = float(row["bookmaker_no_vig"])
            if math.isfinite(implied) and 0 < implied < 1:
                bookmaker.append((implied, y))
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "n": n, "brier": round(brier, 6),
        "log_loss": round(log_loss, 6), "ece": round(ece, 6),
        "confidence_bands": {
            f"{band * 10:02d}-{band * 10 + 9:02d}": {
                "n": len(cell),
                "predicted": round(sum(p for p, _ in cell) / len(cell), 4),
                "actual": round(sum(y for _, y in cell) / len(cell), 4),
            } for band, cell in sorted(bands.items())},
        "leagues": {league: {"n": len(cell),
                             "brier": round(sum((p-y)**2 for p, y in cell)
                                            / len(cell), 6)}
                    for league, cell in by_league.items() if len(cell) >= 30},
        "recent_brier": round(sum((p-y)**2 for p, y, _ in rows[-min(100, n):])
                              / min(100, n), 6),
        "immutable_price_sample": len(quoted),
        "realized_return": (round(sum(y * odds - 1 for _, y, odds in quoted)
                                  / len(quoted), 6) if quoted else None),
        "expected_return_at_price": (round(sum(p * odds - 1
                                               for p, _, odds in quoted)
                                           / len(quoted), 6) if quoted else None),
        "bookmaker_sample": len(bookmaker),
        "bookmaker_brier": (round(sum((p-y)**2 for p, y in bookmaker)
                                   / len(bookmaker), 6) if bookmaker else None),
    }


def evaluate_market(market: str, observations: list[dict]) -> dict:
    """Score only later, immutable outcomes; return advice, never a promotion.

    Each row needs a fixture identity, prediction date, outcome, per-model
    probabilities and a model-specific training cutoff. Missing cutoffs mean
    unverified training overlap and are excluded. Duplicate fixture outcomes
    never add effective sample size.
    """
    policy = market_policy(market)
    models = (policy["champion"], *policy["challengers"])
    samples = {name: [] for name in models}
    paired = {name: [] for name in policy["challengers"]}
    rejected = defaultdict(int)
    seen = set()
    for row in sorted(observations, key=lambda value: str(value.get("date") or "")):
        if row.get("market") != market:
            continue
        identity = row.get("fixture_id")
        if not identity or identity in seen:
            rejected["DUPLICATE_OR_MISSING_FIXTURE"] += 1
            continue
        seen.add(identity)
        try:
            when = date.fromisoformat(str(row["date"])[:10])
            outcome = int(row["outcome"])
            assert outcome in (0, 1)
        except (KeyError, TypeError, ValueError, AssertionError):
            rejected["INVALID_OUTCOME"] += 1
            continue
        probabilities = row.get("model_probabilities") or {}
        cutoffs = row.get("training_cutoffs") or {}
        accepted = {}
        for name in models:
            try:
                probability = float(probabilities[name])
                cutoff = date.fromisoformat(str(cutoffs[name])[:10])
            except (KeyError, TypeError, ValueError):
                rejected["MISSING_PROVENANCE_OR_PROBABILITY"] += 1
                continue
            if not math.isfinite(probability) or not 0 < probability < 1:
                rejected["INVALID_PROBABILITY"] += 1
                continue
            if when <= cutoff:
                rejected["TRAINING_OVERLAP"] += 1
                continue
            accepted[name] = probability
            samples[name].append((probability, outcome, row))
        baseline = accepted.get("base_model")
        if baseline is not None:
            for name in policy["challengers"]:
                challenger = accepted.get(name)
                if challenger is not None:
                    improvement = ((baseline - outcome) ** 2 -
                                   (challenger - outcome) ** 2)
                    paired[name].append((improvement, baseline, challenger,
                                         outcome, row))

    metrics = {name: _metrics(rows) for name, rows in samples.items()}
    comparisons = {}
    for name, rows in paired.items():
        n = len(rows)
        if not n:
            comparisons[name] = {"n": 0, "status": "NO_OOS_EVIDENCE"}
            continue
        gains = [item[0] for item in rows]
        mean = sum(gains) / n
        variance = sum((gain - mean) ** 2 for gain in gains) / max(1, n - 1)
        lower = mean - 1.96 * math.sqrt(variance / n)
        champion_rows = [(base, y, row) for _, base, _, y, row in rows]
        challenger_rows = [(candidate, y, row) for _, _, candidate, y, row in rows]
        champion_metrics = _metrics(champion_rows)
        challenger_metrics = _metrics(challenger_rows)
        status = ("ELIGIBLE_FOR_HUMAN_REVIEW"
                  if n >= MIN_OOS_OBSERVATIONS and lower > 0 and
                  challenger_metrics["log_loss"] <= champion_metrics["log_loss"] and
                  challenger_metrics["ece"] <= champion_metrics["ece"]
                  else "KEEP_CHAMPION")
        comparisons[name] = {
            "n": n, "paired_brier_improvement": round(mean, 6),
            "lower_95pct_improvement": round(lower, 6),
            "status": status, "champion": champion_metrics,
            "challenger": challenger_metrics,
        }
    return {"policy": policy, "metrics": metrics,
            "comparisons": comparisons, "rejected": dict(rejected),
            "automatic_promotion": False}
