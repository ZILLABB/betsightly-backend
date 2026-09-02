from growth.templates import rollover


def _data():
    return {
        "date": "2026-09-02",
        "rollover": {
            "selected": True,
            "day_number": 2,
            "target_days": 3,
            "total_odds": 2.14,
            "hit_probability": 0.51,
            "completion_probability": 0.14,
            "legs": [{
                "home_team": "Home",
                "away_team": "Away",
                "prediction": "Over 1.5 Goals",
                "confidence": 0.82,
                "odds": 1.24,
                "odds_are_real": True,
            }],
            "booking": {
                "status": "active",
                "share_code": "ROLL23",
                "priced_at": "2026-09-02T07:05:00Z",
            },
        },
    }


def test_telegram_rollover_post_contains_day_risk_and_booking_code():
    rendered = rollover(_data(), "telegram")
    text = rendered["text"]
    assert "Day 2 of 3" in text
    assert "Today’s odds: *2.14x*" in text
    assert "*51%*" in text
    assert "*14%*" in text
    assert "ROLL23" in text


def test_rollover_template_skips_when_there_is_no_active_slot():
    data = _data()
    data["rollover"]["selected"] = False
    assert rollover(data, "telegram") is None
