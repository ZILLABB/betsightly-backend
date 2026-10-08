"""Read-only *counterfactual* evidence-gate audit on the staging board.

This is a research diagnostic, NOT a change to publication policy. It keeps
all existing real-price, exact-bookability, trust, probability and conservative
value gates. It asks how many selections fail ONLY the 25-settlement safe-tier
evidence requirement once market trust has already been applied.

Do not use results to publish, book, recommend bets, or claim validated model
accuracy. Market-specific independent prospective calibration is still needed.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight
from leagues.publication_policy import evaluate_leg
from leagues.fixture_ranker import canonical_fixture_recommendations

PRODUCTS = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5")
EVIDENCE_REASON = "INSUFFICIENT_SETTLED_EVIDENCE"


def inspect_market_picks(picks: list[dict], product: str) -> dict:
    """Never changes pick records or evaluates without normal market trust."""
    if product not in PRODUCTS:
        raise ValueError("Unknown official product")
    permitted = canonical_fixture_recommendations(
        picks, include_all_eligible=True,
    )
    if product == "over_1_5":
        permitted = [p for p in permitted if p.get("market") == "over_1_5"]

    metrics: dict[str, dict] = defaultdict(
        lambda: {
            "official_qualified_ids": set(),
            "blocked_only_by_settled_evidence_ids": set(),
            "blocked_by_other_rules_ids": set(),
            "rejection_reasons": Counter(),
            "permitted_selections": 0,
        }
    )
    for candidate in permitted:
        market = str(candidate.get("market") or "unknown")
        event_id = str(candidate.get("match_id") or "")
        if not event_id:
            continue
        row = metrics[market]
        row["permitted_selections"] += 1
        judgment = evaluate_leg(candidate, product)
        reasons = set(judgment["reasons"])
        if not reasons:
            row["official_qualified_ids"].add(event_id)
        elif reasons == {EVIDENCE_REASON}:
            row["blocked_only_by_settled_evidence_ids"].add(event_id)
        else:
            row["blocked_by_other_rules_ids"].add(event_id)
        row["rejection_reasons"].update(judgment["reasons"])

    result = {}
    for market, row in sorted(metrics.items()):
        approved = row["official_qualified_ids"]
        shadow_only = row["blocked_only_by_settled_evidence_ids"] - approved
        result[market] = {
            "post_market_trust_selections": row["permitted_selections"],
            "official_qualified_unique_fixtures": len(approved),
            "evidence_only_blocked_unique_fixtures": len(shadow_only),
            "other_rules_blocked_unique_fixtures": len(row["blocked_by_other_rules_ids"]),
            "counterfactual_without_evidence_gate_unique_fixtures": len(
                approved | shadow_only
            ),
            "rejection_reasons": dict(sorted(row["rejection_reasons"].items())),
        }
    return result


def audit() -> dict:
    db_name = preflight()
    from leagues.engine import prepared_board, kickoff_wat_date

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError("Staging snapshot must be fresh; no refresh performed")
    if not board.get("board_snapshot_id") or not fixtures:
        raise RuntimeError("Staging snapshot must have valid persisted provenance")

    start = (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    dates = [(start + timedelta(days=offset)).isoformat() for offset in range(1, 7)]
    summary = {}
    for product in PRODUCTS:
        by_market = {}
        for day in dates:
            subset = [
                p for p in picks
                if kickoff_wat_date((p.get("_fixture") or {}).get("commence_time")) == day
            ]
            for market, values in inspect_market_picks(subset, product).items():
                existing = by_market.setdefault(
                    market, {
                        "post_market_trust_selections": 0,
                        "official_qualified_unique_fixtures": 0,
                        "evidence_only_blocked_unique_fixtures": 0,
                        "other_rules_blocked_unique_fixtures": 0,
                        "counterfactual_without_evidence_gate_unique_fixtures": 0,
                        "rejection_reasons": Counter(),
                    },
                )
                for field in (
                    "post_market_trust_selections",
                    "official_qualified_unique_fixtures",
                    "evidence_only_blocked_unique_fixtures",
                    "other_rules_blocked_unique_fixtures",
                    "counterfactual_without_evidence_gate_unique_fixtures",
                ):
                    existing[field] += values[field]
                existing["rejection_reasons"].update(values["rejection_reasons"])
        summary[product] = {
            market: {
                **row,
                "rejection_reasons": dict(sorted(row["rejection_reasons"].items())),
            } for market, row in sorted(by_market.items())
        }
    return {
        "mode": "STAGING_ONLY_COUNTERFACTUAL_EVIDENCE_GATE_DIAGNOSIS",
        "database": db_name,
        "snapshot_id": board["board_snapshot_id"],
        "model_candidate_count": len(picks),
        "dates_wat": dates,
        "product_markets": summary,
        "warning": "NOT APPROVED FOR PUBLICATION OR BETTING; evidence requirement NOT relaxed",
        "thresholds_changed": False,
        "published": False,
        "booking_codes_created": False,
        "settlement_triggered": False,
        "provider_refresh_triggered": False,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True))
