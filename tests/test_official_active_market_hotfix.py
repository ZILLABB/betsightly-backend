"""October 9 production hotfix: expand ACTIVE market alternatives, not quality policy."""
from datetime import datetime, timedelta, timezone

from leagues import daily_feed
from leagues import fixture_ranker
from leagues.publication_policy import evaluate_leg
from tests.test_daily_portfolio import _pick


def test_official_preview_preserves_policy_and_exposure_with_all_active_markets(monkeypatch):
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{tomorrow}T18:00:00Z"
    picks = [_pick(n, kickoff) for n in range(25)]
    fixtures = [p["_fixture"] for p in picks]

    original = fixture_ranker.canonical_fixture_recommendations
    ranking_flags = []

    def trace_ranker(selections, **kwargs):
        ranking_flags.append(kwargs.get("include_all_eligible", False))
        return original(selections, **kwargs)

    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations", trace_ranker
    )
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_, **__: {
        "selected": False, "games": [], "chain": [], "chain_length": 0,
    })
    old_cache = dict(daily_feed._accum_cache)
    try:
        preview = daily_feed.build_daily_accumulators(preview={
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "target_wat_date": tomorrow, "picks": picks, "fixtures": fixtures,
        })
        assert ranking_flags == [True, True]
        assert preview["locked"] is False
        assert preview["accumulators"]["_portfolio"]["portfolio_validation"]["valid"] is True
        assert preview["accumulators"]["_portfolio"]["portfolio_validation"]["fixture_overlap_count"] == 0
        assert daily_feed._accum_cache == old_cache
    finally:
        daily_feed._accum_cache.clear()
        daily_feed._accum_cache.update(old_cache)


def test_official_policy_still_rejects_unproven_or_unbookable_even_with_expanded_ranker():
    pick = _pick(0, "2099-01-01T18:00:00Z")
    pick["market"] = "btts_yes"
    pick["safe_tier_eligible"] = False
    pick["market_trust_state"] = "RESTRICTED"
    pick["bookable"] = False
    pick["odds_are_real"] = False
    for product in ("banker", "2_odds", "5_odds", "10_odds", "over_1_5"):
        decision = evaluate_leg(pick, product)
        assert decision["allowed"] is False
        assert "INSUFFICIENT_SETTLED_EVIDENCE" in decision["reasons"]
        assert "NOT_EXACTLY_BOOKABLE" in decision["reasons"]
        assert "ESTIMATED_PRICE" in decision["reasons"]
        assert "MARKET_NOT_TRUSTED" in decision["reasons"]


def test_official_preview_never_runs_pipeline_or_writes(monkeypatch):
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{tomorrow}T18:00:00Z"
    picks = [_pick(n, kickoff) for n in range(12)]
    fixtures = [p["_fixture"] for p in picks]

    def forbidden(*args, **kwargs):
        raise AssertionError("hotfix preview performed a write or full refresh")
    monkeypatch.setattr("leagues.engine.run_pipeline", forbidden)
    monkeypatch.setattr(daily_feed, "_load_locked", forbidden)
    monkeypatch.setattr(daily_feed, "_archive", forbidden)
    monkeypatch.setattr("leagues.picks_db.save_card", forbidden)
    monkeypatch.setattr("leagues.decision_archive.record_daily", forbidden)
    monkeypatch.setattr("leagues.rollover_db.load_chain", forbidden)
    monkeypatch.setattr("leagues.rollover_db.append_day", forbidden)

    result = daily_feed.build_daily_accumulators(preview={
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_wat_date": tomorrow, "picks": picks, "fixtures": fixtures,
    })
    assert result["locked"] is False
    assert result["accumulators"]["_portfolio"]["portfolio_validation"]["valid"] is True
