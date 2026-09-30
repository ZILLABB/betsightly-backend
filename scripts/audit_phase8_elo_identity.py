"""Audit cross-provider Elo team identity against ESPN history.

Provider gaps are reported per league. Comparable leagues are evaluated
independently so one unavailable ESPN league cannot hide strong parity in
another league.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.elo_identity import lookup_rating_entry
from leagues.espn_history_fetch import HistoryMonthUnavailable
from leagues.football_first_challenger import combine_results
from leagues.football_first_runtime_elo import API_LEAGUE_TO_ESPN_SLUG
from leagues.history_months import finished_matches

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = (
    ROOT / "data" / "football_history" / "openfootball_matches.csv"
)
DEFAULT_REPORT = ROOT / "audit" / "phase8_elo_identity.json"

LEAGUE_PARITY_MIN_RESOLVED_RATE = 0.95


def _training_names(
    legacy: pd.DataFrame,
    history: pd.DataFrame,
    start: str,
    end: str,
) -> dict[int, set[str]]:
    combined, _ = combine_results(legacy, history)
    dates = pd.to_datetime(
        combined["date"],
        errors="coerce",
    )
    mask = (
        (dates >= pd.Timestamp(start))
        & (dates <= pd.Timestamp(end))
    )
    subset = combined.loc[mask]

    out: dict[int, set[str]] = {}
    for league_id, group in subset.groupby(
        "league_id"
    ):
        names = set(
            group["home_team"].astype(str)
        )
        names.update(
            group["away_team"].astype(str)
        )
        out[int(league_id)] = names
    return out


def _espn_names(
    league_id: int,
    start: str,
    end: str,
) -> set[str]:
    slug = API_LEAGUE_TO_ESPN_SLUG[
        league_id
    ]
    rows = finished_matches(
        slug,
        start.replace("-", ""),
        end.replace("-", ""),
    )
    names = set()
    for row in rows:
        if row.get("home"):
            names.add(
                str(row["home"])
            )
        if row.get("away"):
            names.add(
                str(row["away"])
            )
    return names


def _compare(
    training: set[str],
    espn: set[str],
) -> dict:
    # Entry values only need to be distinguishable objects for the
    # identity resolver. No Elo rating math is performed in this audit.
    pool = {
        name: {
            "rating": 1500.0,
            "matches": 99,
            "_identity": name,
        }
        for name in espn
    }

    methods = Counter()
    ambiguous = []
    unresolved = []

    for name in sorted(training):
        resolution = lookup_rating_entry(
            name,
            pool,
        )
        status = resolution.get("status")
        method = resolution.get("method") or "unknown"

        if status == "READY":
            methods[method] += 1
        elif status == "AMBIGUOUS":
            ambiguous.append({
                "training_name": name,
                "method": method,
                "candidates": resolution.get(
                    "candidates"
                ) or [],
            })
        else:
            unresolved.append(name)

    resolved = sum(methods.values())
    total = len(training)
    resolved_rate = (
        resolved / total
        if total
        else 0.0
    )

    return {
        "training_names": total,
        "espn_names": len(espn),
        "resolution_methods": dict(methods),
        "exact_provider_name": methods.get(
            "exact_provider_name",
            0,
        ),
        "unique_canonical_match": methods.get(
            "unique_canonical_match",
            0,
        ),
        "unique_strict_equivalent": methods.get(
            "unique_strict_equivalent",
            0,
        ),
        "ambiguous": len(ambiguous),
        "ambiguous_examples": ambiguous[:20],
        "unresolved": len(unresolved),
        "resolved": resolved,
        "resolved_rate": round(
            resolved_rate,
            6,
        ),
        "unresolved_examples": unresolved[:20],
        "league_identity_parity": bool(
            total > 0
            and not ambiguous
            and resolved_rate
            >= LEAGUE_PARITY_MIN_RESOLVED_RATE
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--legacy",
        type=Path,
        default=DEFAULT_LEGACY,
    )
    parser.add_argument(
        "--football-history",
        type=Path,
        default=DEFAULT_HISTORY,
    )
    parser.add_argument(
        "--end",
        default="2026-06-01",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
    )
    parser.add_argument(
        "--league-id",
        type=int,
        action="append",
        choices=sorted(
            API_LEAGUE_TO_ESPN_SLUG
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
    )
    args = parser.parse_args()

    end_dt = datetime.strptime(
        args.end,
        "%Y-%m-%d",
    )
    start = (
        end_dt
        - timedelta(
            days=max(
                30,
                args.days,
            )
        )
    ).date().isoformat()

    ids = (
        args.league_id
        or sorted(
            API_LEAGUE_TO_ESPN_SLUG
        )
    )

    legacy = pd.read_csv(
        args.legacy,
        low_memory=False,
    )
    history = pd.read_csv(
        args.football_history,
        low_memory=False,
    )
    training = _training_names(
        legacy,
        history,
        start,
        args.end,
    )

    rows = []

    for league_id in ids:
        if league_id not in training:
            continue

        slug = API_LEAGUE_TO_ESPN_SLUG[
            league_id
        ]

        try:
            espn = _espn_names(
                league_id,
                start,
                args.end,
            )
        except HistoryMonthUnavailable as exc:
            rows.append({
                "league_id": league_id,
                "league_slug": slug,
                "provider_status": "UNAVAILABLE",
                "provider_error": str(exc),
                "training_names": len(
                    training[league_id]
                ),
                "espn_names": 0,
                "resolution_methods": {},
                "exact_provider_name": 0,
                "unique_canonical_match": 0,
                "unique_strict_equivalent": 0,
                "ambiguous": 0,
                "ambiguous_examples": [],
                "unresolved": 0,
                "resolved": 0,
                "resolved_rate": None,
                "unresolved_examples": [],
                "league_identity_parity": False,
            })
            continue

        comparison = _compare(
            training[league_id],
            espn,
        )
        rows.append({
            "league_id": league_id,
            "league_slug": slug,
            "provider_status": "AVAILABLE",
            "provider_error": None,
            **comparison,
        })

    comparable = [
        row
        for row in rows
        if row["provider_status"]
        == "AVAILABLE"
    ]
    unavailable = [
        row
        for row in rows
        if row["provider_status"]
        == "UNAVAILABLE"
    ]

    training_n = sum(
        row["training_names"]
        for row in comparable
    )
    resolved_n = sum(
        row["resolved"]
        for row in comparable
    )
    ambiguous_n = sum(
        row["ambiguous"]
        for row in comparable
    )
    unresolved_n = sum(
        row["unresolved"]
        for row in comparable
    )

    method_counts = Counter()
    for row in comparable:
        method_counts.update(
            row["resolution_methods"]
        )

    allowlist = [
        row["league_id"]
        for row in comparable
        if row["league_identity_parity"]
    ]
    blocked = [
        row["league_id"]
        for row in comparable
        if not row["league_identity_parity"]
    ]

    report = {
        "schema": 2,
        "experiment": (
            "phase8_elo_identity_parity_v3"
        ),
        "window": {
            "start": start,
            "end": args.end,
        },
        "identity_contract": (
            "elo-team-identity-v3"
        ),
        "league_parity_min_resolved_rate": (
            LEAGUE_PARITY_MIN_RESOLVED_RATE
        ),
        "league_count": len(rows),
        "comparable_league_count": len(
            comparable
        ),
        "provider_unavailable_league_count": len(
            unavailable
        ),
        "provider_unavailable_leagues": [
            {
                "league_id": row[
                    "league_id"
                ],
                "league_slug": row[
                    "league_slug"
                ],
                "error": row[
                    "provider_error"
                ],
            }
            for row in unavailable
        ],
        "training_names": training_n,
        "resolved": resolved_n,
        "resolved_rate": (
            round(
                resolved_n / training_n,
                6,
            )
            if training_n
            else 0.0
        ),
        "resolution_methods": dict(
            method_counts
        ),
        "ambiguous": ambiguous_n,
        "unresolved": unresolved_n,
        "parity_allowlist_league_ids": sorted(
            allowlist
        ),
        "parity_blocked_league_ids": sorted(
            blocked
        ),
        "provider_identity_parity_comparable": bool(
            comparable
            and len(blocked) == 0
            and ambiguous_n == 0
        ),
        "provider_identity_parity_all": bool(
            comparable
            and not unavailable
            and len(blocked) == 0
            and ambiguous_n == 0
        ),
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
        "leagues": rows,
    }

    args.report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.report.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(
        "PHASE 8B.2 ELO IDENTITY "
        "PARITY V2"
    )
    print(
        f"window: {start} -> {args.end}"
    )
    print(
        f"leagues requested: "
        f"{len(rows)}"
    )
    print(
        f"leagues comparable: "
        f"{len(comparable)}"
    )
    print(
        f"provider unavailable: "
        f"{len(unavailable)}"
    )

    for row in unavailable:
        print(
            f"  {row['league_id']} "
            f"{row['league_slug']}: "
            f"{row['provider_error']}"
        )

    print(
        f"training names compared: "
        f"{training_n:,}"
    )
    print(
        f"resolved: {resolved_n:,} "
        f"({report['resolved_rate'] * 100:.2f}%)"
    )
    print(
        "methods: "
        f"{dict(method_counts)}"
    )
    print(
        f"ambiguous: {ambiguous_n:,}"
    )
    print(
        f"unresolved: {unresolved_n:,}"
    )
    print(
        "parity allowlist: "
        f"{sorted(allowlist)}"
    )
    print(
        "parity blocked: "
        f"{sorted(blocked)}"
    )
    print(
        "provider identity parity "
        "(comparable): "
        f"{report['provider_identity_parity_comparable']}"
    )
    print(
        "provider identity parity "
        "(all): "
        f"{report['provider_identity_parity_all']}"
    )
    print(
        "automatic_promotion: False"
    )
    print(
        f"report: "
        f"{args.report.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
