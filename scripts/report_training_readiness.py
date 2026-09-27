"""Create Prompt 4's final training-readiness report."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.training_readiness import derive, load_json, overall_status

DEFAULT_TRAINING = ROOT / "audit" / "training_data_audit.json"
DEFAULT_COVERAGE = ROOT / "audit" / "historical_coverage_gap_audit.json"
DEFAULT_SOURCES = ROOT / "audit" / "historical_source_registry.json"
DEFAULT_JSON = ROOT / "audit" / "training_readiness_report.json"
DEFAULT_MD = ROOT / "TRAINING_READINESS_REPORT.md"


def render(report: dict) -> str:
    baseline = report["baseline"]
    coverage = report["coverage"]
    lines = [
        "# BetSightly Training Readiness Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        f"Overall expansion status: **{report['overall_status']}**",
        "",
        "## Baseline",
        "",
        f"- Raw rows: **{baseline['raw_rows']:,}**",
        f"- Valid finished rows: **{baseline['valid_finished_rows']:,}**",
        f"- Trainable samples: **{baseline['trainable_samples']:,}**",
        f"- Deployed model metadata samples: **{baseline['model_meta_samples']:,}**",
        f"- Baseline reproducible: **{baseline['baseline_reproducible']}**",
        f"- Complete 1X2 odds coverage: **{baseline['complete_1x2_pct']:.2f}%**",
        f"- Complete O/U 2.5 odds coverage: **{baseline['complete_ou25_pct']:.2f}%**",
        f"- Duplicate fixture keys: **{baseline['duplicate_fixture_keys']}**",
        f"- Conflicting fixture keys: **{baseline['conflicting_fixture_keys']}**",
        "",
        "## Expansion coverage",
        "",
        f"- Missing live competitions: **{coverage['missing_live_target_count']}**",
        f"- IDs: `{coverage['missing_live_target_ids']}`",
        f"- Verified free results-history sources: **{coverage['verified_results_history_sources']}**",
        f"- Verified odds-backed sources for those gaps: **{coverage['verified_odds_backed_gap_sources']}**",
        f"- Still unresolved: **{coverage['unresolved_gap_sources']}**",
        "",
        "## Readiness by use case",
        "",
    ]

    for item in report["decisions"]:
        lines += [
            f"### {item['status']} — {item['use_case']}",
            "",
            item["reason"],
            "",
        ]
        if item["blockers"]:
            lines.append("Blockers:")
            for blocker in item["blockers"]:
                lines.append(f"- `{blocker}`")
            lines.append("")
        lines += [
            f"Next action: {item['next_action']}",
            "",
        ]

    lines += [
        "## Decision",
        "",
        "Do **not** retrain or overwrite the deployed 25-feature ensemble yet.",
        "",
        "The current model remains the frozen benchmark. The next implementation "
        "phase should ingest verified results-only sources into a separate "
        "`football_history` dataset, while a separate `market_training` dataset "
        "remains restricted to rows with explicit bookmaker-price provenance.",
        "",
        "Only after those datasets are validated should BetSightly train isolated "
        "challenger models and compare them against the current baseline on "
        "chronological holdouts and live shadow performance.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", type=Path, default=DEFAULT_TRAINING)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    report = derive(
        load_json(args.training.resolve()),
        load_json(args.coverage.resolve()),
        load_json(args.sources.resolve()),
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["overall_status"] = overall_status(report)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.md_out.write_text(render(report), encoding="utf-8")

    print("TRAINING READINESS REPORT")
    print(f"overall: {report['overall_status']}")
    print(
        "baseline: "
        f"trainable={report['baseline']['trainable_samples']:,} "
        f"meta={report['baseline']['model_meta_samples']:,} "
        f"reproducible={report['baseline']['baseline_reproducible']}"
    )
    print(
        "coverage: "
        f"missing={report['coverage']['missing_live_target_count']} "
        f"results_sources={report['coverage']['verified_results_history_sources']} "
        f"odds_sources={report['coverage']['verified_odds_backed_gap_sources']} "
        f"unresolved={report['coverage']['unresolved_gap_sources']}"
    )
    for item in report["decisions"]:
        print(
            f"{item['status']} {item['use_case']}: "
            f"blockers={item['blockers']}"
        )
    print(f"json: {args.json_out}")
    print(f"markdown: {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
