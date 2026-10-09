"""Read-only prospective 1X2 paired champion/challenger report for staging.

This cohort is separate from SportyBet odds captures. Models overlap on fixture
identity, so never pool versions or infer 77 independent games from 77 rows.
No bets, promotions, live adjustments, training, or database writes.
"""
from __future__ import annotations

from sqlalchemy import text

TABLE = "public.football_first_shadow_observations"
MIN_REVIEW_FIXTURES = 300

ACCESS_QUERY = text("""
    SELECT
        to_regclass('public.football_first_shadow_observations')
            IS NOT NULL AS table_exists,
        CASE WHEN to_regclass('public.football_first_shadow_observations')
            IS NOT NULL
        THEN has_table_privilege(
            CURRENT_USER, 'public.football_first_shadow_observations', 'SELECT'
        )
        ELSE FALSE END AS can_select
""")

PAIRED_QUERY = text("""
    SELECT model_version, feature_version,
        COUNT(*) AS paired_observations,
        COUNT(DISTINCT fixture_id) AS distinct_fixtures,
        AVG(
            POWER(champion_away - CASE WHEN outcome_class=0 THEN 1 ELSE 0 END, 2) +
            POWER(champion_draw - CASE WHEN outcome_class=1 THEN 1 ELSE 0 END, 2) +
            POWER(champion_home - CASE WHEN outcome_class=2 THEN 1 ELSE 0 END, 2)
        ) AS champion_multiclass_brier,
        AVG(
            POWER(challenger_away - CASE WHEN outcome_class=0 THEN 1 ELSE 0 END, 2) +
            POWER(challenger_draw - CASE WHEN outcome_class=1 THEN 1 ELSE 0 END, 2) +
            POWER(challenger_home - CASE WHEN outcome_class=2 THEN 1 ELSE 0 END, 2)
        ) AS challenger_multiclass_brier,
        AVG(-LN(GREATEST(0.000000000001,
            CASE WHEN outcome_class=0 THEN champion_away
                 WHEN outcome_class=1 THEN champion_draw
                 ELSE champion_home END
        ))) AS champion_log_loss,
        AVG(-LN(GREATEST(0.000000000001,
            CASE WHEN outcome_class=0 THEN challenger_away
                 WHEN outcome_class=1 THEN challenger_draw
                 ELSE challenger_home END
        ))) AS challenger_log_loss
    FROM public.football_first_shadow_observations
    WHERE status = 'settled'
        AND outcome_class IN (0,1,2)
        AND target = 'match_result'
        AND observed_at < kickoff
        AND settled_at >= kickoff
        AND settlement_source IS NOT NULL
        AND home_score IS NOT NULL AND away_score IS NOT NULL
        AND champion_away BETWEEN 0 AND 1
        AND champion_draw BETWEEN 0 AND 1
        AND champion_home BETWEEN 0 AND 1
        AND challenger_away BETWEEN 0 AND 1
        AND challenger_draw BETWEEN 0 AND 1
        AND challenger_home BETWEEN 0 AND 1
        AND ABS(champion_away + champion_draw + champion_home - 1) < 0.0001
        AND ABS(challenger_away + challenger_draw + challenger_home - 1) < 0.0001
    GROUP BY model_version, feature_version
    ORDER BY model_version, feature_version
""")


def summarize(rows: list[dict]) -> dict:
    """Keep each model version's distinct fixture population separate."""
    cohorts = []
    for item in rows:
        n = int(item["distinct_fixtures"])
        champion = float(item["champion_multiclass_brier"])
        challenger = float(item["challenger_multiclass_brier"])
        cohorts.append({
            "model_version": item["model_version"],
            "feature_version": item["feature_version"],
            "paired_observations": int(item["paired_observations"]),
            "independent_fixtures": n,
            "champion_multiclass_brier": round(champion, 6),
            "challenger_multiclass_brier": round(challenger, 6),
            "challenger_brier_gain": round(champion - challenger, 6),
            "champion_log_loss": round(float(item["champion_log_loss"]), 6),
            "challenger_log_loss": round(float(item["challenger_log_loss"]), 6),
            "minimum_research_review_fixtures": MIN_REVIEW_FIXTURES,
            "below_research_review_minimum": n < MIN_REVIEW_FIXTURES,
        })
    return {
        "status": (
            "DESCRIPTIVE_PAIRED_EVIDENCE_ONLY"
            if cohorts else "NO_VERIFIED_PAIRED_EVIDENCE"
        ),
        "cohorts": cohorts,
        "do_not_sum_fixtures_across_versions": True,
        "linked_to_real_sportybet_closing_odds": False,
        "production_promotion_authorized": False,
        "read_only": True,
        "interpretation": (
            "Each row compares champion and challenger on the same prospective "
            "fixture. Model-version fixture sets may overlap; no pooled "
            "promotion claim, independent odds/CLV evidence, or betting edge."
        ),
    }


def audit_paired_challenger(*, db_engine=None) -> dict:
    if db_engine is None:
        from database import engine
        db_engine = engine
    with db_engine.connect() as conn:
        available = conn.execute(ACCESS_QUERY).mappings().one()
        if not available["table_exists"]:
            return {
                "status": "PROSPECTIVE_PAIRS_TABLE_MISSING",
                "read_only": True,
                "production_promotion_authorized": False,
                "cohorts": [],
            }
        if not available["can_select"]:
            return {
                "status": "STAGING_READONLY_SELECT_GRANT_REQUIRED",
                "table": TABLE,
                "read_only": True,
                "production_promotion_authorized": False,
                "cohorts": [],
                "remediation": (
                    "Grant SELECT on this staging table only to "
                    "betsightly_eval_readonly; never grant write rights."
                ),
            }
        rows = [dict(x) for x in conn.execute(PAIRED_QUERY).mappings()]
    return summarize(rows)
