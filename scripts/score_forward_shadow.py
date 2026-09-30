"""Score immutable forward forecasts only after separate verified settlement.

Input outcome rows must be supplied later with fixture_id, market, won,
verified_at and provider. This script never discovers or changes results.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _band(sample):
    n = int(sample or 0)
    return "0" if n == 0 else ("1-9" if n < 10 else ("10-24" if n < 25 else "25+"))


def _metrics(rows):
    scored = [(float(p), int(won)) for p, won in rows if p is not None]
    if not scored:
        return {"n": 0, "brier": None, "log_loss": None,
                "calibration_error": None}
    n = len(scored)
    brier = sum((p - y) ** 2 for p, y in scored) / n
    log_loss = -sum(y * math.log(max(1e-12, min(1-1e-12, p)))
                    + (1-y) * math.log(max(1e-12, min(1-1e-12, 1-p)))
                    for p, y in scored) / n
    bins = defaultdict(list)
    for p, y in scored:
        bins[min(9, int(p * 10))].append((p, y))
    error = sum(len(group) / n * abs(
        sum(p for p, _ in group) / len(group)
        - sum(y for _, y in group) / len(group))
        for group in bins.values())
    return {"n": n, "brier": round(brier, 6),
            "log_loss": round(log_loss, 6),
            "calibration_error": round(error, 6)}


def score(forecasts: dict, outcomes: list[dict]) -> dict:
    if not forecasts.get("snapshot_id") or not forecasts.get("shadow_records"):
        raise ValueError("immutable forward forecast archive required")
    outcome_map = {}
    for row in outcomes:
        if not row.get("provider") or not row.get("verified_at"):
            raise ValueError("verified provider and observation time required")
        if not isinstance(row.get("won"), bool):
            raise ValueError("settlement outcome must be boolean")
        key = (row["fixture_id"], row["market"])
        if key in outcome_map:
            raise ValueError("duplicate fixture-market settlement")
        outcome_map[key] = row
    seen = set()
    cohorts = defaultdict(list)
    paired = defaultdict(list)
    baseline = {
        (row["fixture_id"], row["market"]): row["probability"]
        for row in forecasts["shadow_records"]
        if row["model"] == "devigged_bookmaker" and not row.get("abstain")
    }
    counts = defaultdict(lambda: {"eligible": 0, "abstained": 0, "scored": 0})
    for row in forecasts["shadow_records"]:
        if row.get("snapshot_id") != forecasts["snapshot_id"]:
            raise ValueError("mixed forecast snapshots")
        key = (row["fixture_id"], row["market"], row["model"])
        if key in seen:
            raise ValueError("duplicate fixture-market-model forecast")
        seen.add(key)
        model = row["model"]
        counts[model]["eligible"] += 1
        if row.get("abstain"):
            counts[model]["abstained"] += 1
            continue
        settlement = outcome_map.get((row["fixture_id"], row["market"]))
        if settlement is None:
            continue
        predicted_at = datetime.fromisoformat(row["predicted_at"])
        kickoff_at = datetime.fromisoformat(row["kickoff_at"])
        verified_at = datetime.fromisoformat(settlement["verified_at"])
        if any(dt.tzinfo is None or dt.utcoffset() is None
               for dt in (predicted_at, kickoff_at, verified_at)):
            raise ValueError("forecast/settlement times must be timezone-aware")
        if not (predicted_at < kickoff_at <= verified_at):
            raise ValueError("forecast/settlement timing invalid")
        counts[model]["scored"] += 1
        cell = (row["probability"], settlement["won"])
        cohorts[(model, "all")].append(cell)
        cohorts[(model, f"market:{row['market']}")].append(cell)
        cohorts[(model, f"competition:{row.get('competition_type')}")].append(cell)
        cohorts[(model, f"sample:{_band(row.get('competition_sample'))}")].append(cell)
        book_p = baseline.get((row["fixture_id"], row["market"]))
        if book_p is not None and row.get("observed_odds") is not None:
            paired[model].append((cell, (book_p, settlement["won"])))
    return {
        "snapshot_id": forecasts["snapshot_id"],
        "models": {model: {
            **count, "coverage": round((count["eligible"] - count["abstained"])
                                      / count["eligible"], 6) if count["eligible"] else None,
            "settled_coverage": round(count["scored"] / count["eligible"], 6)
                                if count["eligible"] else None,
            **_metrics(cohorts[(model, "all")]),
            "bookmaker_relative": {
                "n": len(paired[model]),
                "brier_delta": round(
                    _metrics([ours for ours, _ in paired[model]])["brier"]
                    - _metrics([book for _, book in paired[model]])["brier"], 6)
                if paired[model] else None,
                "log_loss_delta": round(
                    _metrics([ours for ours, _ in paired[model]])["log_loss"]
                    - _metrics([book for _, book in paired[model]])["log_loss"], 6)
                if paired[model] else None,
            },
        } for model, count in counts.items()},
        "cohorts": {f"{model}|{group}": _metrics(rows)
                    for (model, group), rows in cohorts.items() if group != "all"},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("forecasts", type=Path)
    parser.add_argument("outcomes", type=Path)
    args = parser.parse_args()
    print(json.dumps(score(
        json.loads(args.forecasts.read_text(encoding="utf-8")),
        json.loads(args.outcomes.read_text(encoding="utf-8"))), indent=2))
