"""Permission-aware, SELECT-only staging bookmaker-price history diagnostics."""
from __future__ import annotations

from sqlalchemy import text

TABLE = "public.sportybet_odds_history_v1"
ACCESS_QUERY = text("""
    SELECT to_regclass('public.sportybet_odds_history_v1')
           IS NOT NULL AS table_exists,
           CASE WHEN to_regclass('public.sportybet_odds_history_v1')
                IS NOT NULL
                THEN has_table_privilege(
                     CURRENT_USER, 'public.sportybet_odds_history_v1', 'SELECT'
                )
                ELSE FALSE
           END AS can_select
""")

METRICS_QUERY = text("""
    WITH per_market AS (
        SELECT sportybet_event_id, market,
            COUNT(DISTINCT snapshot_id) AS unique_source_snapshots,
            COUNT(DISTINCT captured_at) AS observed_price_moments,
            MIN(captured_at) AS first_price_time,
            MAX(captured_at) AS last_price_time,
            MIN(kickoff) AS fixture_kickoff
        FROM public.sportybet_odds_history_v1
        WHERE quoted_odds > 1 AND captured_at < kickoff
        GROUP BY sportybet_event_id, market
    )
    SELECT
        (SELECT COUNT(*) FROM public.sportybet_odds_history_v1)
            AS immutable_price_rows,
        (SELECT COUNT(DISTINCT snapshot_id)
         FROM public.sportybet_odds_history_v1) AS distinct_snapshots,
        COUNT(*) AS priced_fixture_markets,
        COUNT(*) FILTER (
            WHERE unique_source_snapshots >= 2
              AND observed_price_moments >= 2
        ) AS fixture_markets_with_two_source_snapshots,
        COUNT(*) FILTER (
            WHERE unique_source_snapshots >= 2
              AND observed_price_moments >= 2
              AND first_price_time <= fixture_kickoff - INTERVAL '60 minutes'
              AND last_price_time >= fixture_kickoff - INTERVAL '30 minutes'
        ) AS near_close_research_pairs
    FROM per_market
""")


def audit_odds_archive(*, db_engine=None):
    if db_engine is None:
        from database import engine
        db_engine = engine
    with db_engine.connect() as conn:
        row = conn.execute(ACCESS_QUERY).mappings().one()
        if not row["table_exists"]:
            return {
                "status": "APPEND_ONLY_ODDS_WAREHOUSE_NOT_INITIALIZED",
                "read_only": True, "verified_clv_available": False,
            }
        if not row["can_select"]:
            return {
                "status": "ODDS_WAREHOUSE_SELECT_GRANT_REQUIRED",
                "table": TABLE,
                "read_only": True, "verified_clv_available": False,
            }
        counts = dict(conn.execute(METRICS_QUERY).mappings().one())
    return {
        "status": "APPEND_ONLY_PRICE_HISTORY_DESCRIPTIVE_ONLY",
        **{key: int(value or 0) for key, value in counts.items()},
        "read_only": True,
        "verified_clv_available": False,
        "note": (
            "Two unique source snapshots do not prove a sportsbook closing "
            "line. Only captured provider timestamps are trusted, not "
            "replay or settlement job times."
        ),
    }
