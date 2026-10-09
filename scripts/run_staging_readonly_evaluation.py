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
                ) AS can_change_shadow,
                CASE WHEN to_regclass(
                    'public.football_first_shadow_observations'
                ) IS NOT NULL THEN has_table_privilege(
                    CURRENT_USER,
                    'public.football_first_shadow_observations',
                    'INSERT, UPDATE, DELETE, TRUNCATE'
                ) ELSE FALSE END AS can_change_paired,
                CASE WHEN to_regclass(
                    'public.sportybet_odds_history_v1'
                ) IS NOT NULL THEN has_table_privilege(
                    CURRENT_USER,
                    'public.sportybet_odds_history_v1',
                    'INSERT, UPDATE, DELETE, TRUNCATE'
                ) ELSE FALSE END AS can_change_odds_history
        """)).mappings().one()
        if (row["superuser"] or privilege["can_change_history"]
                or privilege["can_change_shadow"]
                or privilege["can_change_paired"]
                or privilege["can_change_odds_history"]):
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
                 walk: dict | None, preflight_report: dict,
                 settlement: dict | None = None) -> str:
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
            f"- Past-kickoff pending observations awaiting verified results: "
            f"{audit.get('mature_pending_settlement_rows', 0)} "
            f"across {audit.get('mature_pending_settlement_fixtures', 0)} fixtures",
            f"- Voided observations: {audit.get('void_observations', 0)}",
            "- Blockers: " + ", ".join(audit["blockers"]),
            f"- Real bookable settled observations scored: "
            f"{(audit.get('settled_market_scoring') or {}).get('real_bookable_settled_observations', 0)}",
            f"- Distinct fixtures scored: "
            f"{(audit.get('settled_market_scoring') or {}).get('distinct_settled_fixtures', 0)}",
            "- Settled market scores: **descriptive only; no paired champion comparison**",
            f"- Odds history capture snapshots: "
            f"{(audit.get('odds_history_readiness') or {}).get('warehouse_snapshots', 0)}",
            f"- Fixture-market combinations with multiple price captures: "
            f"{(audit.get('odds_history_readiness') or {}).get('fixture_markets_with_multiple_prices', 0)}",
            f"- CLV evidence: **{(audit.get('odds_history_readiness') or {}).get('status', 'UNAVAILABLE')}**",
        ]
        odds_archive = audit.get("append_only_odds_archive") or {}
        lines += [
            "",
            "## Append-only SportyBet price history (independent source timestamps)",
            f"- Archive status: **{odds_archive.get('status', 'UNAVAILABLE')}**",
            f"- Captured snapshots: {odds_archive.get('distinct_snapshots', 0)}",
            f"- Fixture-market pairs across snapshots: "
            f"{odds_archive.get('fixture_markets_with_two_source_snapshots', 0)}",
            "- Verified closing-line value: **not yet available**",
        ]
        paired = audit.get("prospective_match_result_pairs") or {}
        lines += [
            "",
            "## Prospective 1X2 paired champion/challenger (separate from odds)",
            f"- Access/evidence status: **{paired.get('status', 'unavailable')}**",
        ]
        for cohort in paired.get("cohorts") or []:
            lines += [
                f"- {cohort['model_version']}: "
                f"{cohort['independent_fixtures']} independent fixtures, "
                f"champion Brier {cohort['champion_multiclass_brier']}, "
                f"challenger Brier {cohort['challenger_multiclass_brier']}, "
                f"minimum for review {cohort['minimum_research_review_fixtures']}",
            ]
        lines.append(
            "- Paired model evidence has **no matched SportyBet closing odds**; "
            "no model promotion is authorized."
        )
    if settlement is not None:
        lines += [
            "",
            "## Verified-final settlement dry-run (no database writes)",
            f"- Mature observations checked: {settlement['pending_mature_rows_checked']}",
            f"- Verified fixtures: {settlement['verified_fixture_count']}",
            f"- Would settle: {settlement['would_settle']}",
            f"- Would void: {settlement['would_void']}",
            f"- Rows updated: {settlement['rows_updated']}",
            f"- Unresolved reasons: {json.dumps(settlement['unresolved'], sort_keys=True)}",
            f"- Score-provider failures: {json.dumps(settlement['provider_failures'], sort_keys=True)}",
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
    settlement = None
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
    if mode == "all":
        from scripts.settle_staging_market_shadow import reconcile
        settlement = reconcile(write=False)
        (report_dir / "settlement_dry_run.json").write_text(
            json.dumps(settlement, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    summary = make_summary(mode, evidence, walk, safety, settlement=settlement)
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
