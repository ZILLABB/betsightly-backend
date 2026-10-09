"""Read-only staging evidence inventory for real champion/challenger comparison.

A historical market-value test needs matched *pre-match* predictions, odds
actually offered before kickoff, and a verified result for the SAME fixture.
The historical OpenFootball corpus and newly captured October SportyBet
shadow rows must not be joined on guesswork or described as a fair cohort.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import text

from scripts.prepare_staging_board_once import preflight

HISTORY_TABLE = "public.external_historical_results_v1"
SHADOW_TABLE = "public.market_shadow_forecasts_v1"
TABLE_QUERY = text("""
    SELECT to_regclass(:history) AS history_table,
           to_regclass(:shadow) AS shadow_table
""")
INVENTORY_QUERY = text("""
    SELECT
        COUNT(*) AS forecasts,
        COUNT(DISTINCT fixture_id) AS forecast_fixtures,
        COUNT(*) FILTER (
            WHERE odds_are_real = TRUE AND quoted_odds > 1
              AND observed_at < kickoff
        ) AS priced_pre_match,
        COUNT(*) FILTER (
            WHERE odds_are_real = TRUE AND quoted_odds > 1
              AND bookable_at_capture = TRUE AND observed_at < kickoff
        ) AS bookable_pre_match,
        COUNT(*) FILTER (
            WHERE status ILIKE 'settled' AND outcome IS NOT NULL
              AND home_score IS NOT NULL AND away_score IS NOT NULL
        ) AS settled_with_result,
        COUNT(*) FILTER (
            WHERE status ILIKE 'settled' AND outcome IS NOT NULL
              AND home_score IS NOT NULL AND away_score IS NOT NULL
              AND odds_are_real = TRUE AND quoted_odds > 1
              AND bookable_at_capture = TRUE AND observed_at < kickoff
        ) AS settled_real_bookable_pre_match,
        COUNT(*) FILTER (
            WHERE status = 'pending'
              AND kickoff <= NOW() - INTERVAL '3 hours'
              AND observed_at < kickoff
              AND home_score IS NULL AND away_score IS NULL
        ) AS mature_pending_rows,
        COUNT(DISTINCT fixture_id) FILTER (
            WHERE status = 'pending'
              AND kickoff <= NOW() - INTERVAL '3 hours'
              AND observed_at < kickoff
              AND home_score IS NULL AND away_score IS NULL
        ) AS mature_pending_fixtures,
        COUNT(*) FILTER (WHERE status = 'void') AS void_rows,
        COUNT(*) FILTER (WHERE observed_at >= kickoff) AS invalid_prematch_rows,
        MIN(kickoff) AS first_forecast_kickoff,
        MAX(kickoff) AS last_forecast_kickoff
    FROM public.market_shadow_forecasts_v1
""")
HISTORY_QUERY = text("""
    SELECT
        COUNT(*) AS historical_rows,
        COUNT(DISTINCT league_slug) AS historical_leagues,
        MAX(match_date) AS latest_completed_match_date
    FROM public.external_historical_results_v1
""")


def evidence_status(shadow: dict, history: dict) -> dict:
    """No deployment/promotion without a comparable completed cohort."""
    eligible = int(shadow.get("settled_real_bookable_pre_match") or 0)
    completed = int(shadow.get("settled_with_result") or 0)
    first = shadow.get("first_forecast_kickoff")
    last_history = history.get("latest_completed_match_date")
    # UTC time to date is conservative around midnight; never infer exact
    # matching events from a timestamp-range overlap.
    first_date = first.date() if isinstance(first, datetime) else (
        date.fromisoformat(str(first)[:10]) if first else None
    )
    last_date = last_history if isinstance(last_history, date) else (
        date.fromisoformat(str(last_history)[:10]) if last_history else None
    )
    ranges_disjoint = bool(
        first_date is not None and last_date is not None
        and last_date < first_date
    )
    blockers = []
    if eligible == 0:
        blockers.append("NO_SETTLED_REAL_BOOKABLE_PREMATCH_OBSERVATIONS")
    if ranges_disjoint:
        blockers.append("HISTORY_ENDS_BEFORE_FIRST_CAPTURED_ODDS")
    blockers.append("NO_VERIFIED_SAME_FIXTURE_CHAMPION_CHALLENGER_PAIRS")
    blockers.append("NO_HISTORICAL_CLOSING_LINE_MATCHED_COHORT")
    return {
        "status": "CHAMPION_COMPARISON_BLOCKED",
        "shadow_forecasts": int(shadow.get("forecasts") or 0),
        "shadow_unique_fixtures": int(shadow.get("forecast_fixtures") or 0),
        "mature_pending_settlement_rows": int(shadow.get("mature_pending_rows") or 0),
        "mature_pending_settlement_fixtures": int(shadow.get("mature_pending_fixtures") or 0),
        "void_observations": int(shadow.get("void_rows") or 0),
        "invalid_prematch_observations": int(shadow.get("invalid_prematch_rows") or 0),
        "real_priced_pre_match_observations": int(
            shadow.get("priced_pre_match") or 0
        ),
        "real_bookable_pre_match_observations": int(
            shadow.get("bookable_pre_match") or 0
        ),
        "settled_observations_with_scores": completed,
        "settled_real_bookable_pre_match_observations": eligible,
        "external_history_rows": int(history.get("historical_rows") or 0),
        "external_history_leagues": int(history.get("historical_leagues") or 0),
        "last_external_history_date": (
            last_date.isoformat() if last_date else None
        ),
        "first_captured_forecast_kickoff_date": (
            first_date.isoformat() if first_date else None
        ),
        "historical_date_ranges_disjoint": ranges_disjoint,
        "blockers": blockers,
        "source": "staging read-only market shadow plus external historical results",
        "champion_model_unchanged": True,
        "production_promotion_authorized": False,
        "database_writes": False,
        "next_evidence": (
            "Collect verified settlement outcomes and same-fixture pre-match "
            "champion + challenger probabilities, then compare Brier, "
            "calibration and price-relative EV only on matched dates/markets."
        ),
    }


def audit() -> dict:
    database = preflight()
    from database import engine
    with engine.connect() as conn:
        tables = conn.execute(TABLE_QUERY, {
            "history": HISTORY_TABLE, "shadow": SHADOW_TABLE,
        }).mappings().one()
        if tables["history_table"] is None or tables["shadow_table"] is None:
            raise RuntimeError(
                "Missing staging shadow odds or external historical warehouse"
            )
        shadow = dict(conn.execute(INVENTORY_QUERY).mappings().one())
        history = dict(conn.execute(HISTORY_QUERY).mappings().one())
    return {"database": database, **evidence_status(shadow, history)}


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True, default=str))
