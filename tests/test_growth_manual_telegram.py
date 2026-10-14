"""Manual tier Telegram notification must match validated SportyBet booking."""
import pytest
from growth import editorial_telegram as notices


def sample():
    return {
        "editorial_manual": True,
        "total_odds": 2.27,
        "games": [
            {"home_team": "Arsenal", "away_team": "Lille",
             "market": "home_or_draw", "prediction": "Home or Draw"},
        ],
        "booking": {
            "status": "active", "booking_status": "FULL",
            "readback_validation": "PASSED", "share_code": "TEST123",
            "final_booked_legs": [{}],
        },
    }


def test_manual_code_post_is_truthful_and_editorial_not_model_scored():
    result = notices.message_for_manual("2026-10-13", "2_odds", sample())
    body = result["text"]
    assert "Admin-curated" in body
    assert "NOT a model-scored prediction" in body
    assert "TEST123" in body
    assert "2.27x" in body
    assert "Arsenal vs Lille" in body
    assert "No win is guaranteed" in body


@pytest.mark.parametrize("field,value", [
    ("readback_validation", "FAILED"), ("booking_status", "PARTIAL"),
    ("share_code", None), ("final_booked_legs", []),
])
def test_unverified_manual_slips_are_never_announced(field, value):
    result = sample()
    result["booking"][field] = value
    with pytest.raises(ValueError):
        notices.message_for_manual("2026-10-13", "2_odds", result)


def test_manual_outbox_does_not_send_if_telegram_auto_disabled(monkeypatch):
    from growth import store
    from growth import models
    hashes = []
    def save(items):
        hashes.append((items[0]["template"],items[0]["hash"]))
        return {"ids":[42],"created":1,"skipped":0}
    monkeypatch.setattr(store,"store_items",save)
    monkeypatch.setattr(models,"channel_auto_publishes",lambda channel: False)
    a = notices.queue_published_manual("2026-10-13","2_odds",sample())
    b = notices.queue_published_manual("2026-10-13","2_odds",sample())
    assert a["sent"] is False and b["sent"] is False
    assert hashes[0][0] == "manual_2_odds"
    assert hashes[0][1] == hashes[1][1]
