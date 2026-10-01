"""Audit whether existing local historical sources cover live target leagues.

Read-only. It never downloads data, rewrites a dataset, or trains a model.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import runpy
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRAINING = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_GITHUB = ROOT / "data" / "github-football" / "Matches.csv"
DEFAULT_JSON = ROOT / "audit" / "historical_coverage_gap_audit.json"
DEFAULT_MD = ROOT / "HISTORICAL_COVERAGE_GAP_AUDIT.md"

TARGETS = {
    1: {
        "name": "FIFA World Cup",
        "aliases": ["world cup", "fifa world cup"],
    },
    2: {
        "name": "UEFA Champions League",
        "aliases": ["champions league", "uefa champions league"],
    },
    3: {
        "name": "UEFA Europa League",
        "aliases": ["europa league", "uefa europa league", "uefa cup"],
    },
    11: {
        "name": "Copa Sudamericana",
        "aliases": ["copa sudamericana", "sudamericana"],
    },
    13: {
        "name": "Copa Libertadores",
        "aliases": ["copa libertadores", "libertadores"],
    },
    265: {
        "name": "Chilean Primera Division",
        "aliases": [
            "chilean primera division",
            "chile primera division",
            "primera division chile",
            "primera division",
        ],
    },
    292: {
        "name": "K League 1",
        "aliases": ["k league 1", "k league", "kleague"],
    },
    307: {
        "name": "Saudi Pro League",
        "aliases": [
            "saudi pro league",
            "saudi professional league",
            "saudi premier league",
        ],
    },
    848: {
        "name": "UEFA Conference League",
        "aliases": [
            "conference league",
            "uefa conference league",
            "europa conference league",
        ],
    },
}


def norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def target_league_ids() -> set[int]:
    path = ROOT / "services" / "apifootball_service.py"
    if not path.exists():
        return set()
    try:
        ns = runpy.run_path(str(path), run_name="coverage_audit_api_football")
        return {int(x) for x in (ns.get("TARGET_LEAGUE_IDS") or set())}
    except Exception:
        return set()


def training_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    frame = pd.read_csv(path, usecols=lambda c: c == "league_id", low_memory=False)
    values = pd.to_numeric(frame.get("league_id"), errors="coerce")
    return {int(x) for x in values.dropna().astype(int).tolist()}


def _valid_price(series: pd.Series) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce")
    return num.gt(1.0)


def _division_stats(frame: pd.DataFrame, division: str) -> dict:
    subset = frame[frame["Division"].astype(str) == division].copy()
    dates = pd.to_datetime(subset.get("MatchDate"), errors="coerce", utc=True)

    def coverage(cols):
        if any(col not in subset.columns for col in cols):
            return 0.0
        mask = _valid_price(subset[cols[0]])
        for col in cols[1:]:
            mask = mask & _valid_price(subset[col])
        return round(float(mask.mean() * 100.0), 4) if len(subset) else 0.0

    return {
        "division": division,
        "rows": int(len(subset)),
        "date_min": dates.min().date().isoformat() if dates.notna().any() else None,
        "date_max": dates.max().date().isoformat() if dates.notna().any() else None,
        "complete_1x2_pct": coverage(["OddHome", "OddDraw", "OddAway"]),
        "complete_ou25_pct": coverage(["Over25", "Under25"]),
    }


def candidate_divisions(frame: pd.DataFrame, spec: dict) -> list[dict]:
    divisions = sorted({
        str(value).strip()
        for value in frame["Division"].dropna().astype(str)
        if str(value).strip()
    })
    aliases = [norm(a) for a in spec["aliases"]]
    target = norm(spec["name"])
    candidates = []

    for division in divisions:
        dnorm = norm(division)
        if not dnorm:
            continue
        keyword = any(alias in dnorm or dnorm in alias for alias in aliases)
        similarity = max(
            [SequenceMatcher(a=dnorm, b=target).ratio()]
            + [SequenceMatcher(a=dnorm, b=alias).ratio() for alias in aliases]
        )
        if keyword or similarity >= 0.72:
            stats = _division_stats(frame, division)
            stats.update({
                "normalized_division": dnorm,
                "keyword_match": bool(keyword),
                "similarity": round(float(similarity), 4),
            })
            candidates.append(stats)

    candidates.sort(
        key=lambda row: (
            -int(row["keyword_match"]),
            -float(row["similarity"]),
            -int(row["rows"]),
            row["division"],
        )
    )
    return candidates[:20]


def audit(training_path: Path, github_path: Path) -> dict:
    live_ids = target_league_ids()
    train_ids = training_ids(training_path)
    missing = sorted(live_ids - train_ids)

    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "training_csv": str(training_path),
        "github_history_csv": str(github_path),
        "live_target_ids": sorted(live_ids),
        "training_ids": sorted(train_ids),
        "missing_live_target_ids": missing,
        "github_history_available": github_path.exists(),
        "github_history_rows": 0,
        "github_history_divisions": 0,
        "targets": {},
    }

    if not github_path.exists():
        for league_id in missing:
            spec = TARGETS.get(league_id, {"name": str(league_id), "aliases": []})
            report["targets"][str(league_id)] = {
                "name": spec["name"],
                "current_training_covered": False,
                "existing_github_source_status": "FILE_MISSING",
                "candidates": [],
            }
        return report

    usecols = {
        "Division", "MatchDate",
        "OddHome", "OddDraw", "OddAway",
        "Over25", "Under25",
    }
    frame = pd.read_csv(
        github_path,
        usecols=lambda c: c in usecols,
        low_memory=False,
    )
    if "Division" not in frame.columns:
        report["github_history_error"] = "Division column missing"
        return report

    report["github_history_rows"] = int(len(frame))
    report["github_history_divisions"] = int(frame["Division"].nunique(dropna=True))

    for league_id in missing:
        spec = TARGETS.get(
            league_id,
            {"name": f"League {league_id}", "aliases": []},
        )
        candidates = candidate_divisions(frame, spec)
        if not candidates:
            status = "NO_LOCAL_CANDIDATE"
        elif candidates[0]["keyword_match"] and candidates[0]["similarity"] >= 0.85:
            status = "STRONG_LOCAL_CANDIDATE"
        elif candidates[0]["keyword_match"]:
            status = "POSSIBLE_LOCAL_CANDIDATE"
        else:
            status = "FUZZY_REVIEW_REQUIRED"

        report["targets"][str(league_id)] = {
            "name": spec["name"],
            "current_training_covered": False,
            "existing_github_source_status": status,
            "candidates": candidates,
        }

    return report


def render(report: dict) -> str:
    lines = [
        "# BetSightly Historical Coverage Gap Audit",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "Read-only audit. No data was downloaded, rewritten, or used to retrain models.",
        "",
        "## Snapshot",
        "",
        f"- Live target league IDs: **{len(report['live_target_ids'])}**",
        f"- Current training league IDs: **{len(report['training_ids'])}**",
        f"- Missing live target IDs: `{report['missing_live_target_ids']}`",
        f"- Existing GitHub-history file available: **{report['github_history_available']}**",
        f"- Existing GitHub-history rows inspected: **{report['github_history_rows']:,}**",
        f"- Existing GitHub-history divisions: **{report['github_history_divisions']:,}**",
        "",
        "## Missing competition review",
        "",
    ]

    for league_id in report["missing_live_target_ids"]:
        entry = report["targets"].get(str(league_id), {})
        lines += [
            f"### {league_id} — {entry.get('name')}",
            "",
            f"Local source status: **{entry.get('existing_github_source_status')}**",
            "",
        ]
        candidates = entry.get("candidates") or []
        if not candidates:
            lines += ["No plausible local division label was found.", ""]
            continue
        lines += [
            "| Division | Rows | Date range | 1X2 | O/U 2.5 | Similarity |",
            "|---|---:|---|---:|---:|---:|",
        ]
        for item in candidates[:10]:
            lines.append(
                f"| {item['division']} | {item['rows']:,} | "
                f"{item['date_min']} → {item['date_max']} | "
                f"{item['complete_1x2_pct']:.2f}% | "
                f"{item['complete_ou25_pct']:.2f}% | "
                f"{item['similarity']:.3f} |"
            )
        lines.append("")

    lines += [
        "## Interpretation rule",
        "",
        "- `STRONG_LOCAL_CANDIDATE`: likely already present locally, but still requires an explicit division-to-competition mapping before ingestion.",
        "- `POSSIBLE_LOCAL_CANDIDATE`: useful lead; inspect before mapping.",
        "- `FUZZY_REVIEW_REQUIRED`: do not ingest automatically.",
        "- `NO_LOCAL_CANDIDATE`: likely needs another verified free source.",
        "- `FILE_MISSING`: local 228K source is unavailable in this worktree.",
        "",
        "No candidate found by this audit is automatically treated as canonical coverage.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", type=Path, default=DEFAULT_TRAINING)
    parser.add_argument("--github-history", type=Path, default=DEFAULT_GITHUB)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    report = audit(args.training.resolve(), args.github_history.resolve())
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.md_out.write_text(render(report), encoding="utf-8")

    print("HISTORICAL COVERAGE GAP AUDIT")
    print(f"missing live target IDs: {report['missing_live_target_ids']}")
    print(
        "github history: "
        f"available={report['github_history_available']} "
        f"rows={report['github_history_rows']:,} "
        f"divisions={report['github_history_divisions']}"
    )
    for league_id in report["missing_live_target_ids"]:
        item = report["targets"].get(str(league_id), {})
        top = (item.get("candidates") or [{}])[0]
        print(
            f"{league_id} {item.get('name')}: "
            f"{item.get('existing_github_source_status')} | "
            f"top={top.get('division')} "
            f"rows={top.get('rows')} "
            f"1x2={top.get('complete_1x2_pct')} "
            f"ou25={top.get('complete_ou25_pct')}"
        )
    print(f"json: {args.json_out}")
    print(f"markdown: {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
