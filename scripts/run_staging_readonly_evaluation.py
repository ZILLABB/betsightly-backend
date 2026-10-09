"""Staging-only, read-only GitHub Actions entry point for model validation.

Requires a dedicated, unprivileged, SELECT-only PostgreSQL login. Prevents
accidental evaluation against production DB or permissive admin credentials.
Reports contain aggregate scores and evidence only; no connection URL.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import text

from scripts.prepare_staging_board_once import (
    STAGING_DATABASE_NAME, preflight,
)


def readonly_actions_preflight() -> dict:
    """Check host identity, concrete connected DB, session and role rights."""
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Read-only runner requires GitHub Actions")
    if os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise RuntimeError("Only manual workflow_dispatch is authorized")
    ref = os.getenv("GITHUB_REF", "")
    if ref != (
        "refs/heads/feature/daily-tier-reach-and-builder-supply-20261009"
    ):
        raise RuntimeError("This workflow is staging-branch-only")
    if os.getenv("ENVIRONMENT") != "staging":
        raise RuntimeError("ENVIRONMENT must be staging")
    if os.getenv("ENABLE_BACKGROUND_JOBS") != "false":
        raise RuntimeError("ENABLE_BACKGROUND_JOBS must be false")
    if not os.getenv("DATABASE_URL", "").startswith(
        ("postgresql://", "postgres://")
    ):
        raise RuntimeError("A dedicated PostgreSQL staging secret is required")
    if not os.getenv("PGOPTIONS", "").find("default_transaction_read_only=on") >= 0:
        raise RuntimeError("Postgres session must default to read-only")
    actual_database = preflight()
    if actual_database != STAGING_DATABASE_NAME:
        raise RuntimeError("Staging DB identity mismatch")

    from database import engine
    with engine.connect() as conn:
        if conn.execute(text("SHOW transaction_read_only")).scalar() != "on":
            raise RuntimeError("Database session is not read-only")
        row = conn.execute(text("""
            SELECT CURRENT_USER AS role_name,
                   (SELECT rolsuper FROM pg_roles
                    WHERE rolname = CURRENT_USER) AS superuser,
                   to_regclass(
                       'public.external_historical_results_v1'
                   ) IS NOT NULL AS history_available,
                   to_regclass(
                       'public.market_shadow_forecasts_v1'
                   ) IS NOT NULL AS shadow_available
        """)).mappings().one()
        if not row["history_available"] or not row["shadow_available"]:
            raise RuntimeError("Required staging evidence tables are absent")
        privilege = conn.execute(text("""
            SELECT
                has_table_privilege(
                    CURRENT_USER,
                    'public.external_historical_results_v1',
                    'INSERT, UPDATE, DELETE, TRUNCATE'
                ) AS can_change_history,
                has_table_privilege(
                    CURRENT_USER,
                    'public.market_shadow_forecasts_v1',
                    'INSERT, UPDATE, DELETE, TRUNCATE'
                ) AS can_change_shadow
        """)).mappings().one()
        if (row["superuser"] or privilege["can_change_history"]
                or privilege["can_change_shadow"]):
            raise RuntimeError(
                "Refusing database role with write access; use SELECT-only "
                "staging evaluation credentials"
            )
    return {
        "database": actual_database,
        "read_only": True,
        "staging_only": True,
        "role_checked_without_exposing_credentials": True,
    }


def make_summary(mode: str, audit: dict | None,
                 walk: dict | None, preflight_report: dict) -> str:
    lines = [
        "# BetSightly staging model-evaluation report",
        "",
        f"- Mode: **{mode}**",
        f"- Database: **{preflight_report['database']}**",
        "- Read-only, staging branch, manual execution: **verified**",
        "- Champion model and production publishing: **unchanged**",
    ]
    if audit is not None:
        lines += [
            "",
            "## Same-fixture odds and settlement evidence",
            f"- Evidence status: **{audit['status']}**",
            f"- Real bookable pre-match: {audit['real_bookable_pre_match_observations']}",
            f"- Settled comparable observations: "
            f"{audit['settled_real_bookable_pre_match_observations']}",
            "- Blockers: " + ", ".join(audit["blockers"]),
        ]
    if walk is not None:
        lines += [
            "",
            "## Four-fold walk-forward research",
            f"- Valid folds: {walk['evaluated_folds']}/{walk['requested_folds']}",
            "| Market | Folds won vs pooled | Folds won vs league |"
            " Improvement vs pooled | Improvement vs league |",
            "|---|---:|---:|---:|---:|",
        ]
        for market, result in walk["markets"].items():
            lines.append(
                f"| {market} | {result.get('winning_folds', 'n/a')} | "
                f"{result.get('folds_beating_league_conditional_baseline', 'n/a')} | "
                f"{result.get('weighted_improvement', 'n/a')} | "
                f"{result.get('weighted_improvement_vs_league_conditional', 'n/a')} |"
            )
    lines += [
        "",
        "**No result in this report authorizes promotion, betting claims, "
        "or relaxation of official publication rules.**",
    ]
    return "\n".join(lines) + "\n"


def run(mode: str, report_dir: Path) -> dict:
    if mode not in {"all", "evidence", "walkforward"}:
        raise ValueError("Unsupported analysis mode")
    safety = readonly_actions_preflight()
    report_dir.mkdir(parents=True, exist_ok=True)
    evidence = None
    walk = None
    if mode in {"all", "evidence"}:
        from scripts.audit_staging_model_comparison_evidence import audit
        evidence = audit()
        (report_dir / "evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    if mode in {"all", "walkforward"}:
        from scripts.export_staging_history_training import training_data
        data = training_data(evaluate_walkforward=True)
        walk = data["walk_forward_evaluation"]
        (report_dir / "walkforward.json").write_text(
            json.dumps(data, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    summary = make_summary(mode, evidence, walk, safety)
    (report_dir / "summary.md").write_text(summary, encoding="utf-8")
    return {
        "status": "STAGING_READONLY_EVALUATED",
        "mode": mode, "database": safety["database"],
        "report_files": sorted(path.name for path in report_dir.iterdir()),
        "production_unchanged": True,
        "promotion_authorized": False,
        "sufficient_champion_comparison": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "evidence", "walkforward"),
                        default="all")
    parser.add_argument("--reports", default="staging_evaluation_reports")
    args = parser.parse_args()
    result = run(args.mode, Path(args.reports))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
