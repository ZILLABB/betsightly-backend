from datetime import datetime, timedelta, timezone

import pytest

from leagues.market_quotes import exact_total_probability, total_quote
from leagues.predictor import predict


NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)


def _odds(line, over=.4, under=.6, *, captured=None, period="full_game"):
    return {"total_quotes": [{
        "market": "total_goals", "period": period, "line": line,
        "over_odds": 2.4, "under_odds": 1.6,
        "implied_over": over, "implied_under": under,
        "captured_at": captured.isoformat() if captured else None,
        "source": "test",
    }]}


@pytest.mark.parametrize("line", [1.5, 2.5, 3.5, 4.5])
def test_total_quote_is_exact_to_requested_line(line):
    odds = _odds(line)
    assert exact_total_probability(odds, line, "over") == .4
    for other in {1.5, 2.5, 3.5, 4.5} - {line}:
        assert exact_total_probability(odds, other, "over") is None


def test_total_quote_missing_stale_and_malformed_are_not_market_evidence():
    assert total_quote({}, 2.5)["status"] == "MISSING"
    stale = _odds(2.5, captured=NOW - timedelta(hours=2))
    assert total_quote(stale, 2.5, now=NOW)["status"] == "STALE"
    malformed = _odds(2.5)
    malformed["total_quotes"][0]["implied_over"] = "bad"
    assert total_quote(malformed, 2.5, now=NOW)["status"] == "MALFORMED"
    assert total_quote(_odds(2.5, period="first_half"), 2.5)["status"] == "WRONG_PERIOD"


def test_predictor_never_labels_a_3_5_quote_as_over_2_5_probability():
    base = {
        "home_win": .45, "draw": .27, "away_win": .28,
        "avg_goals": 2.5, "over_1_5": .72, "btts": .5,
        "matches": 100, "base_rate_source": "test",
    }
    wrong_line = predict({
        "home": {"name": "A"}, "away": {"name": "B"},
        "odds": _odds(3.5, over=.2, under=.8),
    }, base)
    exact_line = predict({
        "home": {"name": "A"}, "away": {"name": "B"},
        "odds": _odds(2.5, over=.2, under=.8),
    }, base)
    assert exact_line["probabilities"]["over_2_5"] == .2
    assert wrong_line["probabilities"]["over_2_5"] != .2
