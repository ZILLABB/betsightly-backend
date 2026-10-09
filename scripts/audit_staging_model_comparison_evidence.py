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
# Descriptive market scores on the same real, bookable, prematch and
# independently settled evidence. Outcomes on one fixture are correlated:
# 'observations' is NOT a sample size of independent football matches.
SETTLED_MARKET_METRICS_QUERY = text("""
    SELECT model_version, market,
           COUNT(*) AS observations,
           COUNT(DISTINCT fixture_id) AS independent_fixtures,
           SUM(CASE WHEN outcome = 1 THEN 1 ELSE 0 END) AS won_observations,
           AVG(probability) AS avg_predicted_probability,
           AVG(outcome::float) AS empirical_win_fraction,
           AVG(POWER(probability - outcome, 2)) AS binary_brier,
           AVG(-outcome * LN(GREATEST(probability, 0.000000000001))
               -(1-outcome)*LN(GREATEST(1-probability, 0.000000000001)))
               AS binary_log_loss
    FROM public.market_shadow_forecasts_v1
    WHERE status = 'settled'
      AND outcome IN (0, 1)
      AND probability BETWEEN 0 AND 1
      AND odds_are_real = TRUE AND quoted_odds > 1
      AND bookable_at_capture = TRUE AND observed_at < kickoff
      AND home_score IS NOT NULL AND away_score IS NOT NULL
      AND settlement_source IS NOT NULL AND settled_at >= kickoff
    GROUP BY model_version, market
    ORDER BY model_version, market
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
        scores = [
            dict(row) for row in conn.execute(
                SETTLED_MARKET_METRICS_QUERY
            ).mappings()
        ]
    score_count = sum(int(item["observations"]) for item in scores)
    scored_fixtures = None
    if score_count:
        with engine.connect() as conn:
            scored_fixtures = conn.execute(text("""
                SELECT COUNT(DISTINCT fixture_id)
                FROM public.market_shadow_forecasts_v1
                WHERE status = 'settled'
                  AND outcome IN (0,1)
                  AND probability BETWEEN 0 AND 1
                  AND odds_are_real AND quoted_odds > 1
                  AND bookable_at_capture AND observed_at < kickoff
                  AND home_score IS NOT NULL AND away_score IS NOT NULL
                  AND settlement_source IS NOT NULL AND settled_at >= kickoff
            """)).scalar()
    report = evidence_status(shadow, history)
    report["settled_market_scoring"] = {
        "status": "DESCRIPTIVE_ONLY_NO_PAIRED_CHAMPION_COMPARISON",
        "real_bookable_settled_observations": score_count,
        "distinct_settled_fixtures": int(scored_fixtures or 0),
        "model_market_rows": scores,
        "data_policy": (
            "Same-fixture markets are correlated. Do not interpret rows "
            "as independent matches or use tiny samples to promote models."
        ),
        "model_promotion_authorized": False,
    }
    return {"database": database, **report}


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True, default=str))
