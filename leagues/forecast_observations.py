"""Canonical, deduplicated settled forecast observations.

One fixture-market outcome is one calibration observation even when the same
forecast appeared in several products. The earliest immutable published
snapshot wins deterministically; later copies only add source/category
metadata and never rewrite its probability.
"""

from __future__ import annotations

import re
from typing import Iterable


def _market_key(leg: dict) -> str:
    market = str(leg.get("market_key") or leg.get("market") or "").strip()
    generic_markets = {"goals", "match_result", "double_chance", "dnb"}
    if market and market not in generic_markets:
        return market
    label = str(leg.get("prediction") or "").lower()
    patterns = (
        (r"over\s*1[.,]5", "over_1_5"),
        (r"over\s*2[.,]5", "over_2_5"),
        (r"under\s*2[.,]5", "under_2_5"),
        (r"under\s*3[.,]5", "under_3_5"),
        (r"under\s*4[.,]5", "under_4_5"),
    )
    for pattern, key in patterns:
        if re.search(pattern, label):
            return key
    return market or "unknown"


def forecast_identity(leg: dict, fallback_date: str = "") -> str:
    market = _market_key(leg)
    fixture_date = str(leg.get("commence_time") or leg.get("kickoff")
                       or leg.get("date") or fallback_date)[:10]
    match_id = str(leg.get("match_id") or leg.get("fixture_id") or "").strip()
    if match_id:
        fixture = match_id
    else:
        def normalize(value: object) -> str:
            return re.sub(r"[^a-z0-9]", "", str(value).lower())

        home = normalize(leg.get("home_team"))
        away = normalize(leg.get("away_team"))
        fixture = f"{home}|{away}"
    return f"{fixture_date}|{fixture}|{market}"


def _record_order(record: dict, source_rank: int) -> tuple:
    return (
        str(record.get("created_at") or record.get("published_at")
            or record.get("date") or "9999"),
        source_rank,
        int(record.get("archive_id") or record.get("id") or 0),
        str(record.get("category") or ""),
    )


def deduplicate_forecasts(
    published_slips: Iterable[dict],
    rollover_days: Iterable[dict] = (),
) -> list[dict]:
    candidates: list[dict] = []

    for slip in published_slips:
        for leg in slip.get("picks") or []:
            if leg.get("status") not in ("won", "lost"):
                continue
            probability = leg.get("confidence")
            raw_probability = leg.get("raw_confidence")
            if probability is None and raw_probability is None:
                continue
            canonical_probability = (
                probability if probability is not None else raw_probability
            )
            canonical_raw = (
                raw_probability if raw_probability is not None else probability
            )
            candidates.append({
                "identity": forecast_identity(
                    leg, str(slip.get("date") or "")
                ),
                "market": _market_key(leg),
                "probability": float(canonical_probability),
                "raw_probability": float(canonical_raw),
                "won": leg.get("status") == "won",
                "policy_version": slip.get("policy_version"),
                "category": str(slip.get("category") or "unknown"),
                "source": "published",
                "order": _record_order(slip, 0),
            })

    for day in rollover_days:
        for leg in day.get("picks") or []:
            if leg.get("status") not in ("won", "lost"):
                continue
            probability = leg.get("confidence")
            raw_probability = leg.get("raw_confidence")
            if probability is None and raw_probability is None:
                continue
            canonical_probability = (
                probability if probability is not None else raw_probability
            )
            canonical_raw = (
                raw_probability if raw_probability is not None else probability
            )
            candidates.append({
                "identity": forecast_identity(leg, str(day.get("date") or "")),
                "market": _market_key(leg),
                "probability": float(canonical_probability),
                "raw_probability": float(canonical_raw),
                "won": leg.get("status") == "won",
                "policy_version": day.get("policy_version"),
                "category": "rollover",
                "source": "rollover",
                "order": _record_order(day, 1),
            })

    canonical: dict[str, dict] = {}
    for candidate in sorted(candidates, key=lambda item: item["order"]):
        identity = candidate["identity"]
        current = canonical.get(identity)
        if current is None:
            canonical[identity] = {
                **candidate,
                "categories": [candidate["category"]],
                "sources": [candidate["source"]],
                "duplicate_count": 1,
            }
            continue
        current["duplicate_count"] += 1
        if candidate["category"] not in current["categories"]:
            current["categories"].append(candidate["category"])
        if candidate["source"] not in current["sources"]:
            current["sources"].append(candidate["source"])

    return list(canonical.values())


def collect_forecast_observations(limit_days: int = 365) -> list[dict]:
    from leagues.picks_db import get_history
    from leagues.rollover_db import history as rollover_history

    return deduplicate_forecasts(
        get_history(limit_days=limit_days),
        rollover_history(limit_days=limit_days),
    )
