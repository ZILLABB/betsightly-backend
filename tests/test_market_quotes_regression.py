from datetime import datetime, timedelta, timezone
from leagues.market_quotes import total_quote, exact_total_probability

NOW = datetime(2026, 9, 17, 14, tzinfo=timezone.utc)

def quote(**overrides):
    q = dict(market="total_goals", period="full_game", line=2.5,
             implied_over=.48, implied_under=.52, over_odds=2.05,
             under_odds=1.8, captured_at=NOW.isoformat(), source="test")
    q.update(overrides)
    return q

def test_total_goals_rejects_corners_even_at_exact_line():
    odds={"total_quotes":[quote(market="corners")]}
    assert total_quote(odds,2.5,now=NOW)["status"] == "WRONG_MARKET"
    assert exact_total_probability(odds,2.5,"over") is None

def test_total_goals_checks_all_candidates_and_accepts_exact_market():
    odds={"total_quotes":[quote(market="corners"),quote()]}
    assert total_quote(odds,2.5,now=NOW)["status"] == "EXACT"

def test_total_goals_rejects_future_quote():
    odds={"total_quotes":[quote(captured_at=(NOW+timedelta(hours=1)).isoformat())]}
    assert total_quote(odds,2.5,now=NOW)["status"] == "FUTURE"

def test_total_goals_tolerates_small_clock_skew_only():
    odds={"total_quotes":[quote(captured_at=(NOW+timedelta(seconds=30)).isoformat())]}
    assert total_quote(odds,2.5,now=NOW)["status"] == "EXACT"

def test_total_goals_invalid_timestamp_is_not_fresh():
    odds={"total_quotes":[quote(captured_at="not-a-date")]}
    assert total_quote(odds,2.5,now=NOW)["status"] == "MALFORMED"

def test_total_goals_rejects_nonfinite_implied():
    odds={"total_quotes":[quote(implied_over=float('nan'))]}
    assert total_quote(odds,2.5,now=NOW)["status"] == "MALFORMED"

def test_total_goals_rejects_wrong_period_and_line():
    assert total_quote({"total_quotes":[quote(period="first_half")]},2.5,now=NOW)["status"] == "WRONG_PERIOD"
    assert total_quote({"total_quotes":[quote(line=3.5)]},2.5,now=NOW)["status"] == "MISSING"
