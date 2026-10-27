"""Replay guardrail: expose missing evidence without promoting a market.

Run locally:
  python scripts/replay_market_evidence.py --output data/replay-candidate
  python scripts/replay_market_evidence.py --output data/replay-candidate --require-over05
This never mutates publication, production DB, booking, or model state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.historical_replay import load_and_deduplicate, replay, write_artifacts  # noqa: E402
from leagues.market_registry import MARKETS  # noqa: E402

DATASET_PATHS = {
    "api_football": "data/api-football/matches.csv",
    "github_football": "data/github-football/Matches.csv",
}


def readiness_report(market_summary: dict, *, require_over05: bool = False) -> dict:
    """Coverage report based on real, chronological historical replay results.

    Large counts of derived observations do not amount to bookmaker benchmarking
    or proof of profitability. Public eligibility is decided separately by
    production trust, bookmaker and product policies.
    """
    monitored = (
        "over_0_5", "over_1_5", "over_2_5",
        "home_over_0_5", "away_over_0_5",
        "home_over_1_5", "away_over_1_5",
        "btts_yes", "btts_no",
    )
    rows = {}
    for market in monitored:
        cell = market_summary.get(market) or {}
        n = int(cell.get("n") or 0)
        bookmaker_n = int(cell.get("bookmaker_n") or 0)
        ece = cell.get("ece")
        rows[market] = {
            "observations": n,
            "ece_pp": round(float(ece) * 100, 3) if ece is not None else None,
            "bookmaker_observations": bookmaker_n,
            "benchmark_coverage": "MEASURED" if bookmaker_n else "MISSING",
            "historical_replay": "SUFFICIENT_FOR_REVIEW" if n >= 200 else "MISSING_OR_SPARSE",
            "policy": MARKETS[market].public_policy,
            "activation": MARKETS[market].activation,
            "note": (
                "Not independently bookmaker-benchmarked; never infer betting edge from ECE alone."
                if not bookmaker_n else
                "Bookmaker benchmark available; evaluate positive skill and recency separately."
            ),
        }
    missing = [m for m, row in rows.items() if row["observations"] < 200]
    return {
        "historical_evidence_only": True,
        "production_promotion_authorized": False,
        "missing_replay_markets": missing,
        "over05_replay_present": rows["over_0_5"]["observations"] >= 200,
        "market_evidence": rows,
        "gate_passed": not require_over05 or rows["over_0_5"]["observations"] >= 200,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/replay-candidate",
                        help="Isolated output directory. Never overwrite deployed replay by default.")
    parser.add_argument("--require-over05", action="store_true",
                        help="Fail if Over 0.5 is absent or fewer than 200 valid historical outcomes.")
    args = parser.parse_args(argv)
    sources = {key: ROOT / path for key, path in DATASET_PATHS.items()}
    missing = [str(p) for p in sources.values() if not p.is_file()]
    if missing:
        parser.error("Missing licensed/local replay input files: " + ", ".join(missing))
    rows, provenance = load_and_deduplicate(sources["api_football"], sources["github_football"])
    result = replay(rows)
    report = readiness_report(result["market_summary"], require_over05=args.require_over05)
    output = args.output.resolve()
    if output == (ROOT / "data/replay").resolve():
        parser.error("Refusing to overwrite approved replay directly; review candidate artifacts first")
    write_artifacts(result, provenance, output, DATASET_PATHS)
    (output / "market_readiness_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "generated_at": (output / "replay_metadata.json").exists(),
        "output": str(output),
        "run": result["run"],
        "coverage": {key: val["observations"] for key,val in report["market_evidence"].items()},
        "missing": report["missing_replay_markets"],
        "benchmark_gaps": [key for key,val in report["market_evidence"].items()
                           if val["bookmaker_observations"] == 0],
        "gate_passed": report["gate_passed"],
    }, sort_keys=True))
    return 0 if report["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
