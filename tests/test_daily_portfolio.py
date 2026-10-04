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


def test_official_products_have_no_exact_selection_overlap_when_board_is_sufficient(monkeypatch):
    target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"
    picks = [_pick(index, kickoff) for index in range(48)]
    fixtures = [pick["_fixture"] for pick in picks]

    monkeypatch.setattr("leagues.engine.run_pipeline", lambda **_: (picks, fixtures))
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: target_date)
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _: None)
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_, **kw: {
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
    assert all(entry["decision"] != "CONTROLLED_OVERLAP_QUALITY_PRESERVED"
               for entry in diagnostics.values())
    assert accumulators["_portfolio"]["portfolio_version"] == "official_exposure_v1"
    assert accumulators["_portfolio"]["portfolio_validation"]["valid"] is True
    final_ids = [
        selection_id
        for product in diagnostics.values()
        for selection_id in product["final_selection_ids"]
    ]
    assert len(final_ids) == len(set(final_ids))


def test_rollover_selection_is_excluded_from_later_official_products(monkeypatch):
    target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"
    picks = [_pick(index, kickoff) for index in range(48)]
    fixtures = [pick["_fixture"] for pick in picks]
    rollover_game = dict(picks[0])
    rollover_game.update({
        "home_team": "Home 0", "away_team": "Away 0",
        "market_key": picks[0]["market"],
    })

    monkeypatch.setattr("leagues.engine.run_pipeline", lambda **_: (picks, fixtures))
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: target_date)
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _: None)
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_, **kw: {
        "selected": True, "games": [rollover_game], "chain": [], "chain_length": 1,
        "total_odds": 1.3, "today_hit_probability": .72,
    })
    monkeypatch.setattr(daily_feed, "_archive", lambda *_: None)
    monkeypatch.setattr("leagues.picks_db.save_card", lambda *_: False)
    daily_feed._accum_cache.update({"result": None, "ts": 0})

    result = daily_feed.build_daily_accumulators(force=True)
    products = result["accumulators"]["_portfolio"]["products"]
    rollover_identity = products["rollover"]["final_selection_ids"][0]
    assert all(
        rollover_identity not in entry["final_selection_ids"]
        for name, entry in products.items() if name != "rollover"
    )


def test_october_three_shared_losses_cannot_be_republished_in_5_and_10(monkeypatch):
    """Regression for the 2026-10-03 5x/10x correlated-loss incident."""
    target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"
    picks = [_pick(index, kickoff) for index in range(56)]
    incident = [
        ("estonia-luxembourg", "Estonia", "Luxembourg", "over_1_5", "Over 1.5 Goals"),
        ("ivory-coast-cameroon", "Ivory Coast", "Cameroon", "dnb_home", "Ivory Coast Draw No Bet"),
        ("newells-lanus", "Newell's Old Boys", "Lanús", "over_1_5", "Over 1.5 Goals"),
    ]
    for pick, (match_id, home, away, market, prediction) in zip(picks, incident):
        pick.update({"match_id": match_id, "market": market, "prediction": prediction})
        pick["_fixture"].update({"match_id": match_id, "home": {"name": home}, "away": {"name": away}})
    fixtures = [pick["_fixture"] for pick in picks]

    monkeypatch.setattr("leagues.engine.run_pipeline", lambda **_: (picks, fixtures))
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: target_date)
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _: None)
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_, **kw: {
        "selected": False, "games": [], "chain": [], "chain_length": 0,
    })
    monkeypatch.setattr(daily_feed, "_archive", lambda *_: None)
    monkeypatch.setattr("leagues.picks_db.save_card", lambda *_: False)
    daily_feed._accum_cache.update({"result": None, "ts": 0})

    products = daily_feed.build_daily_accumulators(force=True)["accumulators"]["_portfolio"]["products"]
    assert not (set(products["5_odds"]["final_selection_ids"])
                & set(products["10_odds"]["final_selection_ids"]))
    assert all(
        decision["decision"] != "CONTROLLED_OVERLAP_QUALITY_PRESERVED"
        for decision in products.values()
    )



def test_rollover_fixture_cannot_reappear_under_different_market(monkeypatch):
    """Same match cannot decide Rollover and another official slip."""
    target_date = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"

    picks = [_pick(index, kickoff) for index in range(6)]
    shared = picks[0]
    fixtures = [pick["_fixture"] for pick in picks]

    # Rollover owns the same fixture, but deliberately under a different
    # market/prediction so exact-selection de-duplication alone cannot catch it.
    rollover_game = {
        "match_id": shared["match_id"],
        "home_team": shared["_fixture"]["home"]["name"],
        "away_team": shared["_fixture"]["away"]["name"],
        "market": "under_4_5",
        "market_key": "under_4_5",
        "prediction": "Under 4.5 Goals",
        "odds": 1.20,
        "confidence": .80,
    }

    monkeypatch.setattr(
        daily_feed,
        "_build_rollover",
        lambda *_, **kw: {
            "selected": True,
            "games": [rollover_game],
            "chain": [],
            "chain_length": 1,
            "total_odds": 1.20,
            "today_hit_probability": .80,
        },
    )

    # Force Banker to want the canonical pick from that exact same fixture.
    # If the fixture is absent, there is intentionally no fallback banker.
    import leagues.selection as selection

    def fixture_only_banker(pool, *args, **kwargs):
        hit = next(
            (
                pick for pick in pool
                if pick["match_id"] == shared["match_id"]
            ),
            None,
        )
        if not hit:
            return [], 0.0, 0.0
        return [hit], float(hit["odds"]), float(hit["confidence"])

    monkeypatch.setattr(
        selection,
        "select_banker",
        fixture_only_banker,
    )

    result = daily_feed.build_daily_accumulators(
        preview={
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "target_wat_date": target_date,
            "picks": picks,
            "fixtures": fixtures,
        }
    )

    portfolio = result["accumulators"]["_portfolio"]
    banker = portfolio["products"]["banker"]

    assert banker["independent_selection_ids"]
    assert banker["final_selection_ids"] == []
    assert banker["decision"] == "WITHHELD_FOR_FIXTURE_EXPOSURE"

    validation = portfolio["portfolio_validation"]
    assert validation["fixture_overlap_count"] == 0
    assert validation["max_fixture_exposure"] <= 1


def test_daily_preview_uses_same_selector_without_publication_writes(monkeypatch):
    target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"
    picks = [_pick(index, kickoff) for index in range(12)]
    fixtures = [pick["_fixture"] for pick in picks]

    def forbidden(*args, **kwargs):
        raise AssertionError("preview attempted publication or provider I/O")

    monkeypatch.setattr("leagues.engine.run_pipeline", forbidden)
    monkeypatch.setattr(daily_feed, "_load_locked", forbidden)
    monkeypatch.setattr(daily_feed, "_archive", forbidden)
    monkeypatch.setattr("leagues.picks_db.save_card", forbidden)
    monkeypatch.setattr("leagues.decision_archive.record_daily", forbidden)
    monkeypatch.setattr("leagues.rollover_db.load_chain", forbidden)
    monkeypatch.setattr("leagues.rollover_db.append_day", forbidden)
    old_cache = dict(daily_feed._accum_cache)
    try:
        result = daily_feed.build_daily_accumulators(preview={
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "target_wat_date": target_date,
            "picks": picks, "fixtures": fixtures,
        })
        assert result["accumulators"]["2_odds"]["selected"]
        assert result["locked"] is False
        assert daily_feed._accum_cache == old_cache
    finally:
        daily_feed._accum_cache.clear()
        daily_feed._accum_cache.update(old_cache)
