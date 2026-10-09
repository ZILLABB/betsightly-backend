"""No champion-vs-challenger edge claims without settled paired fixtures."""
from datetime import date, datetime, timezone

from scripts.audit_staging_model_comparison_evidence import (
    evidence_status, INVENTORY_QUERY, HISTORY_QUERY,
    SETTLED_MARKET_METRICS_QUERY,
)


def test_disjoint_historical_football_and_october_odds_are_not_a_fair_cohort():
    shadow = {
        "forecasts": 4733, "forecast_fixtures": 322,
        "priced_pre_match": 3600, "bookable_pre_match": 3200,
        "settled_with_result": 0,
        "settled_real_bookable_pre_match": 0,
        "first_forecast_kickoff": datetime(
            2026, 10, 9, tzinfo=timezone.utc,
        ),
    }
    history = {
        "historical_rows": 9004, "historical_leagues": 19,
        "latest_completed_match_date": date(2026, 9, 20),
    }
    result = evidence_status(shadow, history)
    assert result["historical_date_ranges_disjoint"] is True
    assert result["production_promotion_authorized"] is False
    assert "HISTORY_ENDS_BEFORE_FIRST_CAPTURED_ODDS" in result["blockers"]
    assert "NO_SETTLED_REAL_BOOKABLE_PREMATCH_OBSERVATIONS" in result["blockers"]
    assert result["database_writes"] is False
    assert result["mature_pending_settlement_rows"] == 0
    assert result["mature_pending_settlement_fixtures"] == 0


def test_even_settled_rows_cannot_prove_champion_comparison_without_pair():
    result = evidence_status(
        {
            "forecasts": 100, "settled_with_result": 60,
            "settled_real_bookable_pre_match": 52,
            "first_forecast_kickoff": datetime(2026, 9, 15),
        },
        {"historical_rows": 1200,
         "latest_completed_match_date": date(2026, 9, 20)},
    )
    assert "HISTORY_ENDS_BEFORE_FIRST_CAPTURED_ODDS" not in result["blockers"]
    assert "NO_VERIFIED_SAME_FIXTURE_CHAMPION_CHALLENGER_PAIRS" in result["blockers"]
    assert result["production_promotion_authorized"] is False


def test_inventory_queries_are_read_only_and_require_real_prematch_odds():
    for q in (INVENTORY_QUERY, HISTORY_QUERY):
        sql = str(q).upper()
        assert sql.strip().startswith("SELECT")
        assert all(word not in sql for word in (
            "DELETE FROM", "UPDATE ", "INSERT INTO", "DROP TABLE",
        ))
    statement = str(INVENTORY_QUERY)
    assert "observed_at < kickoff" in statement
    assert "bookable_at_capture = TRUE" in statement
    assert "home_score IS NOT NULL" in statement
    assert "away_score IS NOT NULL" in statement
    assert "mature_pending_rows" in statement
    assert "mature_pending_fixtures" in statement
    assert "NOW() - INTERVAL '3 hours'" in statement


def test_settled_market_scoring_filters_real_prematch_verified_rows():
    sql = str(SETTLED_MARKET_METRICS_QUERY).upper()
    assert sql.strip().startswith("SELECT")
    assert "STATUS = 'SETTLED'" in sql
    assert "OUTCOME IN (0, 1)" in sql
    assert "BOOKABLE_AT_CAPTURE = TRUE" in sql
    assert "ODDS_ARE_REAL = TRUE" in sql
    assert "OBSERVED_AT < KICKOFF" in sql
    assert "COUNT(DISTINCT FIXTURE_ID)" in sql
    assert "SETTLEMENT_SOURCE IS NOT NULL" in sql
    assert "SETTLED_AT >= KICKOFF" in sql
    assert "BINARY_BRIER" in sql
    assert "BINARY_LOG_LOSS" in sql
    assert all(word not in sql for word in (
        "DELETE FROM", "UPDATE ", "INSERT INTO", "DROP TABLE"
    ))
