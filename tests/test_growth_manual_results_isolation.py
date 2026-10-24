"""Telegram results show editorial wins/losses without contaminating model metrics."""
from datetime import datetime, timedelta, timezone

from growth import dataset, templates


def _date_yesterday():
    return (datetime.now(timezone.utc) + timedelta(hours=1)
            - timedelta(days=1)).strftime("%Y-%m-%d")


def test_recent_telegram_results_keeps_manual_separate(monkeypatch):
    from leagues import picks_db, rollover_db, editorial_settlement

    yesterday = _date_yesterday()
    monkeypatch.setattr(picks_db, "get_history", lambda **kw: [])
    monkeypatch.setattr(picks_db, "performance_summary", lambda **kw: {})
    monkeypatch.setattr(
        picks_db, "product_performance_summary",
        lambda **kw: {
            "accounting_version": "test", "won": 2, "lost": 1,
            "settled": 3, "win_rate": 2 / 3,
            "pending": 0, "void": 0, "oldest_pending_date": None,
        },
    )
    # Last night's manually published Rollover must NOT be reported again as
    # an official engine slip: it belongs to the editorial outcomes block.
    monkeypatch.setattr(
        rollover_db, "history",
        lambda **kw: [{
            "date": yesterday, "status": "won", "day_number": 1,
            "picks": [{"editorial_manual": True}],
        }],
    )
    monkeypatch.setattr(
        editorial_settlement, "editorial_result_history",
        lambda **kw: {
            "status": "success", "results": [
                {"date": yesterday, "tier": "rollover",
                 "status": "won", "total_odds": 2.45, "games": [{}]},
                {"date": yesterday, "tier": "10_odds",
                 "status": "lost", "total_odds": 10.24, "games": [{}]},
                {"date": yesterday, "tier": "5_odds",
                 "status": "pending", "total_odds": 5.11, "games": [{}]},
            ],
        },
    )

    report = dataset._recent_results()
    assert report["won"] == 2
    assert report["lost"] == 1
    assert report["settled"] == 3
    assert report["rollover_settled"] == []
    assert report["manual_record"] == {
        "won": 1, "lost": 1, "void": 0, "pending": 1,
        "settled": 2, "win_rate": 0.5,
    }
    assert len(report["manual_yesterday"]) == 3

    result = templates.results({"results": report}, "telegram")
    assert result is not None
    message = result["text"]
    assert "*Official slip record*" in message
    assert "*Manual picks · admin curated*" in message
    assert "✅ Rollover (2.45x)" in message
    assert "❌ 10 Odds (10.24x)" in message
    assert "⏳ 5 Odds (5.11x)" in message
    assert "never train or calibrate" in message
    # The separated block must not introduce a second official rollover row.
    assert "Rollover Day 1" not in message


def test_telegram_reports_manual_outcomes_even_if_no_model_slips_settled():
    result = templates.results({
        "date": "2026-10-15",
        "results": {
            "window_days": 7, "won": 0, "lost": 0,
            "settled": 0, "win_rate": None, "pending_products": 0,
            "slips_settled": [], "rollover_settled": [],
            "manual_record": {
                "won": 1, "lost": 0, "pending": 0, "settled": 1,
            },
            "manual_yesterday": [
                {"tier": "5_odds", "status": "won", "total_odds": 5.24},
            ],
        },
    }, "telegram")
    assert result and "✅ 5 Odds (5.24x)" in result["text"]


def test_telegram_distinguishes_overdue_score_verification_from_live_match():
    result = templates.results({
        "date": "2026-10-24",
        "results": {
            "window_days": 7, "won": 0, "lost": 0,
            "settled": 0, "win_rate": None, "pending_products": 0,
            "slips_settled": [], "rollover_settled": [],
            "manual_record": {
                "won": 0, "lost": 0, "pending": 1, "settled": 0,
            },
            "manual_yesterday": [{
                "tier": "10_odds", "status": "pending",
                "total_odds": 11.57, "score_verification_delayed": True,
                "games": [
                    {"status": "won"}, {"status": "won"},
                    {"status": "pending"}, {"status": "pending"},
                ],
            }],
        },
    }, "telegram")
    assert result is not None
    message = result["text"]
    assert "2/4 legs verified" in message
    assert "final-score verification delayed" in message
    assert "⚠️ 10 Odds (11.57x)" in message
    assert "official" not in message.lower() or "Official slip record" in message
