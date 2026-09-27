"""Report historical source coverage by use case.

This script does not download or ingest data.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.historical_source_registry import (
    SOURCES,
    eligible_for_current_market_feature_training,
    summary,
)

DEFAULT_JSON = ROOT / "audit" / "historical_source_registry.json"
DEFAULT_MD = ROOT / "HISTORICAL_SOURCE_REGISTRY.md"


def render(payload: dict) -> str:
    lines = [
        "# BetSightly Historical Source Registry",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "This registry distinguishes football-results coverage from bookmaker-odds-backed ML training coverage.",
        "",
        "## Snapshot",
        "",
        f"- Missing live competitions tracked: **{payload['tracked_gap_count']}**",
        f"- Free results-history source identified: **{payload['results_history_covered_count']}**",
        f"- Free odds-backed source identified: **{payload['odds_backed_covered_count']}**",
        f"- Immediately eligible for the current market-feature ensemble: **{payload['current_market_model_eligible_count']}**",
        f"- Still unresolved: **{payload['unresolved_count']}**",
        "",
        "## Competition sources",
        "",
        "| ID | Competition | Provider | Class | Results | Odds history | Current ensemble eligible | Verification |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ]
    for item in payload["sources"]:
        lines.append(
            f"| {item['league_id']} | {item['competition']} | "
            f"{item['provider']} | {item['source_class']} | "
            f"{'yes' if item['results_history'] else 'no'} | "
            f"{'yes' if item['bookmaker_odds_history'] else 'no'} | "
            f"{'yes' if item['current_market_model_eligible'] else 'no'} | "
            f"{item['verification']} |"
        )

    lines += [
        "",
        "## Guardrail",
        "",
        "Results-only data may expand form, base-rate, ELO/Dixon-Coles, replay, and future football-first models. "
        "It must not be silently mixed into the current 25-feature market-price ensemble as though bookmaker odds were present.",
        "",
        "The next ingestion phase should therefore create two explicit datasets:",
        "",
        "1. `football_history`: result/identity history, allowed to use verified results-only sources.",
        "2. `market_training`: rows with explicit bookmaker-price provenance suitable for market-feature model training.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    payload = summary()
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["sources"] = []
    for source in SOURCES:
        item = source.as_dict()
        item["current_market_model_eligible"] = (
            eligible_for_current_market_feature_training(source)
        )
        payload["sources"].append(item)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.md_out.write_text(render(payload), encoding="utf-8")

    print("HISTORICAL SOURCE REGISTRY")
    print(
        f"results-history covered: "
        f"{payload['results_history_covered_count']}/{payload['tracked_gap_count']}"
    )
    print(
        f"odds-backed covered: "
        f"{payload['odds_backed_covered_count']}/{payload['tracked_gap_count']}"
    )
    print(
        "current market-model eligible: "
        f"{payload['current_market_model_eligible_count']}/{payload['tracked_gap_count']}"
    )
    print(f"unresolved: {payload['unresolved_count']}")
    for item in payload["sources"]:
        print(
            f"{item['league_id']} {item['competition']}: "
            f"{item['provider']} {item['source_class']} "
            f"results={item['results_history']} "
            f"odds={item['bookmaker_odds_history']} "
            f"eligible={item['current_market_model_eligible']}"
        )
    print(f"json: {args.json_out}")
    print(f"markdown: {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
