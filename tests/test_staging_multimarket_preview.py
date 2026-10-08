"""Opt-in multi-market preview cannot change any published or live path."""
from datetime import datetime, timedelta, timezone

from leagues import daily_feed


def test_multimarket_is_staging_preview_only(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("BETSIGHTLY_STAGING_BOARD_ONCE", "CONFIRM_STAGING_ONLY")
    monkeypatch.setenv("BETSIGHTLY_PREVIEW_ALL_MARKETS", "1")
    assert daily_feed._staging_multi_market_preview({"picks": []}) is True
    assert daily_feed._staging_multi_market_preview(None) is False

    monkeypatch.setenv("ENVIRONMENT", "production")
    assert daily_feed._staging_multi_market_preview({"picks": []}) is False
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("BETSIGHTLY_STAGING_BOARD_ONCE")
    assert daily_feed._staging_multi_market_preview({"picks": []}) is False
    monkeypatch.setenv("BETSIGHTLY_STAGING_BOARD_ONCE", "CONFIRM_STAGING_ONLY")
    monkeypatch.setenv("BETSIGHTLY_PREVIEW_ALL_MARKETS", "0")
    assert daily_feed._staging_multi_market_preview({"picks": []}) is False


def test_preview_passes_all_active_markets_only_when_opted_in(monkeypatch):
    from leagues import engine, fixture_ranker
    from tests.test_daily_portfolio import _pick

    date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{date}T18:00:00Z"
    picks = [_pick(n, kickoff) for n in range(12)]
    fixtures = [p["_fixture"] for p in picks]
    calls = []
    original = fixture_ranker.canonical_fixture_recommendations

    def recorder(picks, **kwargs):
        calls.append(kwargs.get("include_all_eligible", False))
        return original(picks, **kwargs)

    monkeypatch.setattr(fixture_ranker, "canonical_fixture_recommendations", recorder)
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_, **__: {
        "selected": False, "games": [], "chain": [], "chain_length": 0,
    })
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("BETSIGHTLY_STAGING_BOARD_ONCE", "CONFIRM_STAGING_ONLY")

    def forbidden(*_, **__):
        raise AssertionError("preview must never publish, fetch or settle")

    monkeypatch.setattr(engine, "run_pipeline", forbidden)
    monkeypatch.setattr(daily_feed, "_archive", forbidden)
    monkeypatch.setattr(daily_feed, "_load_locked", forbidden)
    monkeypatch.setattr("leagues.picks_db.save_card", forbidden)

    args = {"preview": {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_wat_date": date, "picks": picks, "fixtures": fixtures,
    }}

    monkeypatch.setenv("BETSIGHTLY_PREVIEW_ALL_MARKETS", "0")
    ordinary = daily_feed.build_daily_accumulators(**args)
    assert ordinary["locked"] is False
    assert calls and all(x is False for x in calls)

    calls.clear()
    monkeypatch.setenv("BETSIGHTLY_PREVIEW_ALL_MARKETS", "1")
    expanded = daily_feed.build_daily_accumulators(**args)
    assert expanded["locked"] is False
    assert calls and calls[0] is True
    assert expanded["accumulators"]["_portfolio"]["publication_policy"][
        "staging_multi_market_preview"
    ] is True
    assert expanded["accumulators"]["_portfolio"]["portfolio_validation"]["valid"] is True
    assert ordinary["accumulators"]["_portfolio"]["publication_policy"][
        "staging_multi_market_preview"
    ] is False
