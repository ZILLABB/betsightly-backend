"""Regression: manual/editorial picks must not be advertised as 1% model picks."""
from growth.dataset import _leg
from growth.templates import daily_5, accumulator, codes, best_pick


def _editorial():
    return _leg({
        "match_id": "sportybet:123",
        "home_team": "Lens", "away_team": "Sporting",
        "league": "Champions League",
        "kickoff": "2099-10-13T16:45:00+00:00",
        "prediction": "Over 1.5 Goals",
        "market": "over_1_5",
        "odds": 1.17, "odds_are_real": True,
        "editorial_manual": True,
        "model_probability_available": False,
    }, "2_odds")


def test_editorial_leg_is_explicitly_unscored():
    leg = _editorial()
    assert leg["confidence"] == 0.0  # compatibility with historic clients
    assert leg["model_probability_available"] is False
    assert leg["editorial_manual"] is True


def test_telegram_daily_five_never_renders_fake_one_percent():
    payload = daily_5({"date": "2026-10-13", "daily_top_5": [_editorial()]}, "telegram")
    assert "Confidence: Not model-scored" in payload["text"]
    assert "Source: Admin-curated" in payload["text"]
    assert "Confidence: 1%" not in payload["text"]
    assert "not the complete tier ticket" in payload["text"]


def test_manual_accumulator_does_not_claim_zero_percent_landing():
    tier = {
        "key": "2_odds", "label": "2 Odds", "selected": True,
        "legs": [_editorial()], "total_odds": 2.27,
        "hit_probability": 0.0, "model_probability_available": False,
        "booking_verified": False, "actionable": True,
    }
    payload = accumulator({"date": "2026-10-13", "two_odds": tier}, "telegram")
    assert "no model-estimated landing probability" in payload["text"]
    assert "0% of the time" not in payload["text"]
    assert "Not model-scored" in payload["text"]


def test_manual_best_pick_does_not_claim_model_probability():
    payload = best_pick({"date": "2026-10-13", "best_pick": _editorial()}, "telegram")
    assert "Admin-curated" in payload["text"]
    assert "Model confidence: 1%" not in payload["text"]


