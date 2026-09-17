from datetime import datetime, timedelta, timezone

from leagues import daily_feed


def _pick(index: int, kickoff: str) -> dict:
    markets = ["over_1_5", "under_3_5", "home_or_draw", "dnb_home", "home_win"]
    groups = ["goals", "goals", "double_chance", "dnb", "match_result"]
    market = markets[index % len(markets)]
    fixture = {
        "match_id": f"fixture-{index}", "commence_time": kickoff,
        "home": {"name": f"Home {index}", "logo": None},
        "away": {"name": f"Away {index}", "logo": None},
        "league": "Portfolio League", "league_slug": "portfolio",
        "competition_type": "LEAGUE", "competition_historical_sample": 100,
    }
    confidence = .72
    return {
        "match_id": fixture["match_id"], "market": market,
        "market_group": groups[index % len(groups)],
        "prediction": market, "confidence": confidence,
        "raw_confidence": confidence, "odds": 1.35,
        "odds_are_real": True, "odds_provider": "SportyBet",
        "market_margin": .05, "bookable": True,
        "market_implied_probability": .71, "ml_confidence": .71,
        "expected_value": -.028, "edge": .01,
        "safe_tier_eligible": True, "calibration_group": market,
        "calibration_sample": 100,
        "trust": {
            "evidence_state": "SUPPORTED", "evidence_strength": .9,
            "evidence_adjusted_probability": confidence,
            "lower_reliability_bound": .69, "trust_grade": "A",
        },
        "_fixture": fixture,
        "_model": {
            "expected_goals": {"home": 1.5, "away": 1.1, "total": 2.6},
            "probabilities": {"draw": .25}, "has_market": True,
        },
    }


def test_daily_products_are_built_independently_before_diversification(monkeypatch):
    target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"
    picks = [_pick(index, kickoff) for index in range(12)]
    fixtures = [pick["_fixture"] for pick in picks]

    monkeypatch.setattr("leagues.engine.run_pipeline", lambda **_: (picks, fixtures))
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: target_date)
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _: None)
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_: {
        "selected": False, "games": [], "chain": [], "chain_length": 0,
    })
    monkeypatch.setattr(daily_feed, "_archive", lambda *_: None)
    monkeypatch.setattr("leagues.picks_db.save_card", lambda *_: False)
    daily_feed._accum_cache.update({"result": None, "ts": 0})

    result = daily_feed.build_daily_accumulators(force=True)
    accumulators = result["accumulators"]

    assert accumulators["2_odds"]["selected"] is True
    assert accumulators["5_odds"]["selected"] is True
    assert accumulators["10_odds"]["selected"] is True
    diagnostics = accumulators["_portfolio"]["products"]
    assert diagnostics["2_odds"]["independent_odds"] > 0
    assert diagnostics["5_odds"]["independent_odds"] > 0
    assert diagnostics["10_odds"]["independent_odds"] > 0
    assert all(
        entry["decision"] in {
            "INDEPENDENT_BEST", "DIVERSIFIED_WITHIN_UNCERTAINTY",
            "CONTROLLED_OVERLAP_QUALITY_PRESERVED",
        }
        for entry in diagnostics.values()
    )
