"""An empty Over 1.5 slate must explain Rollover's prior fixture claims."""
from datetime import datetime, timedelta, timezone

from leagues import daily_feed
from tests.test_daily_portfolio import _pick


def test_rollover_reserved_over15_games_have_exposure_explanation(monkeypatch):
    target = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    picks = [_pick(i, f"{target}T18:00:00Z") for i in (0, 5, 10)]
    for p in picks:
        p["market"] = "over_1_5"
        p["market_group"] = "goals"
        p["prediction"] = "Over 1.5 Goals"
    # This is an already-qualified stage owned by Rollover, not an untrusted
    # set of selections we can duplicate into the singles product.
    rollover_games = [
        {**p, "market_key": p["market"],
         "home_team": p["_fixture"]["home"]["name"],
         "away_team": p["_fixture"]["away"]["name"]}
        for p in picks
    ]
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *a, **kw: {
        "selected": True, "games": rollover_games,
        "total_odds": round(1.45 ** 3, 2),
        "today_hit_probability": 0.34,
        "chain": [], "chain_length": 1,
    })

    card = daily_feed.build_daily_accumulators(preview={
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_wat_date": target,
        "picks": picks,
        "fixtures": [p["_fixture"] for p in picks],
    })["accumulators"]
    over = card["over_1_5"]
    assert not over["selected"]
    assert over["result_status"] == "EXPOSURE_CAPPED"
    assert "Rollover" in over["reason"]
    assert "confidence bar" not in over["reason"]
    allocation = card["_portfolio"]["over_1_5_allocation"]
    assert allocation["eligible_before_exposure"] == 3
    assert allocation["already_reserved_eligible"] == 3
    assert allocation["exposure_exhausted"] is True
    assert daily_feed.all_daily_fixture_conflicts(card) == []
