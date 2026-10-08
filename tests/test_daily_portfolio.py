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
        "raw_confidence": confidence, "odds": 1.45,
        "odds_are_real": True, "odds_provider": "SportyBet",
        "market_margin": .05, "bookable": True,
        "market_implied_probability": .68, "ml_confidence": .71,
        "expected_value": .044, "edge": .04,
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
    """Recreate the 2026-10-03 correlated 5x/10x decision shape."""
    target_date = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"

    picks = [_pick(index, kickoff) for index in range(12)]
    incident = [
        (
            "estonia-luxembourg",
            "Estonia",
            "Luxembourg",
            "over_1_5",
            "Over 1.5 Goals",
        ),
        (
            "ivory-coast-cameroon",
            "Ivory Coast",
            "Cameroon",
            "dnb_home",
            "Ivory Coast Draw No Bet",
        ),
        (
            "newells-lanus",
            "Newell's Old Boys",
            "Lan?s",
            "over_1_5",
            "Over 1.5 Goals",
        ),
    ]

    for pick, (
        match_id, home, away, market, prediction
    ) in zip(picks[:3], incident):
        pick.update({
            "match_id": match_id,
            "market": market,
            "prediction": prediction,
        })
        pick["_fixture"].update({
            "match_id": match_id,
            "home": {"name": home},
            "away": {"name": away},
        })

    incident_ids = {
        daily_feed._selection_identity(pick)
        for pick in picks[:3]
    }
    alternative_ids = {
        pick["match_id"] for pick in picks[3:6]
    }

    monkeypatch.setattr(
        daily_feed,
        "_build_rollover",
        lambda *_, **kw: {
            "selected": False,
            "games": [],
            "chain": [],
            "chain_length": 0,
        },
    )

    # Keep earlier official products out of this regression so we can prove
    # specifically that independent 5x and 10x both want the incident legs.
    monkeypatch.setattr(
        "leagues.selection.select_banker",
        lambda *_, **kw: ([], 0.0, 0.0),
    )

    def fake_select_tier(
        pool,
        target,
        max_picks,
        min_confidence,
        min_ev,
        prefer="joint",
        band_low=0.80,
        canonicalize=True,
    ):
        by_match = {
            str(pick["match_id"]): pick for pick in pool
        }

        if target == 2.0:
            return (([], 0.0, 0.0), "No 2x needed in this regression.")

        incident_available = [
            pick for pick in picks[:3]
            if pick["match_id"] in by_match
        ]

        # This is the pre-fix incident shape: independently, BOTH 5x and 10x
        # want the same three football opinions.
        if len(incident_available) == 3 and target in {5.0, 10.0}:
            return (
                (
                    [by_match[pick["match_id"]]
                     for pick in incident_available],
                    5.10 if target == 5.0 else 10.20,
                    0.34 if target == 5.0 else 0.24,
                ),
                None,
            )

        # After 5x claims those fixtures, 10x must use a different qualifying
        # set rather than silently republishing the same losses.
        alternatives = [
            by_match[pick["match_id"]]
            for pick in picks[3:6]
            if pick["match_id"] in by_match
        ]
        if target == 10.0 and len(alternatives) == 3:
            return ((alternatives, 9.40, 0.22), None)

        return (([], 0.0, 0.0), "No qualifying independent alternative.")

    monkeypatch.setattr(daily_feed, "_select_tier", fake_select_tier)

    result = daily_feed.build_daily_accumulators(
        preview={
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "target_wat_date": target_date,
            "picks": picks,
            "fixtures": [pick["_fixture"] for pick in picks],
        }
    )

    products = result["accumulators"]["_portfolio"]["products"]

    independent_five = set(
        products["5_odds"]["independent_selection_ids"]
    )
    independent_ten = set(
        products["10_odds"]["independent_selection_ids"]
    )
    final_five = set(products["5_odds"]["final_selection_ids"])
    final_ten = set(products["10_odds"]["final_selection_ids"])

    # Prove the test actually recreated the incident rather than merely
    # checking two unrelated final sets.
    assert incident_ids <= independent_five
    assert incident_ids <= independent_ten

    # 5x may keep the independent set, but 10x must no longer share it.
    assert incident_ids <= final_five
    assert not (incident_ids & final_ten)
    assert not (final_five & final_ten)

    assert {
        selection_id.split("|", 1)[0]
        for selection_id in final_ten
    } == alternative_ids

    assert products["10_odds"]["decision"] == "DIVERSIFIED"




def test_rollover_fixture_cannot_reappear_under_different_market(monkeypatch):
    """Same match cannot decide Rollover and another official slip."""
    target_date = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"

    picks = [_pick(index, kickoff) for index in range(6)]
    shared = picks[0]
    shared["confidence"] = .80
    shared["raw_confidence"] = .80
    shared["ml_confidence"] = .80
    shared["market_implied_probability"] = .68
    shared["expected_value"] = .088
    shared["trust"]["evidence_adjusted_probability"] = .80
    shared["trust"]["lower_reliability_bound"] = .79
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
        # This regression tests fixture exposure for a PUBLISHED Rollover.
        "odds": 1.30,
        "confidence": .80,
        "market_floor_eligible": True,
        "safe_tier_eligible": True,
        "market_trust_state": "TRUSTED",
        "bookable": True,
        "odds_are_real": True,
        "league_slug": "portfolio",
        "competition_type": "LEAGUE",
    }

    monkeypatch.setattr(
        daily_feed,
        "_build_rollover",
        lambda *_, **kw: {
            "selected": True,
            "games": [rollover_game],
            "chain": [],
            "chain_length": 1,
            "total_odds": 1.30,
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


def _available_now_game(match_id: str, market: str = "over_1_5") -> dict:
    return {
        "match_id": match_id,
        "market": market,
        "market_key": market,
        "prediction": market,
        "home_team": f"Home {match_id}",
        "away_team": f"Away {match_id}",
    }


def test_available_now_final_portfolio_reserves_rollover_and_all_official_tiers():
    rollover = {"games": [_available_now_game("A", "under_3_5")]}
    accumulators = {
        "banker": {"selected": True, "games": [_available_now_game("B")]},
        "2_odds": {"selected": True, "games": [
            _available_now_game("C"), _available_now_game("D"),
        ]},
        "5_odds": {"selected": True, "games": [
            _available_now_game("E"), _available_now_game("F"), _available_now_game("G"),
        ]},
        "10_odds": {"selected": True, "games": [
            _available_now_game("H"), _available_now_game("I"), _available_now_game("J"),
        ]},
        # Independent singles must not participate in this accumulator cap.
        "over_1_5": {"selected": True, "games": [_available_now_game("B")]},
    }

    portfolio = daily_feed._validate_bookable_now_portfolio(accumulators, rollover)

    assert portfolio["portfolio_validation"] == {
        "exact_selection_overlap_count": 0,
        "fixture_overlap_count": 0,
        "max_selection_exposure": 1,
        "max_fixture_exposure": 1,
        "fixture_count": 10,
        "selection_count": 10,
        "valid": True,
    }
    assert not portfolio["withheld_products"]
    assert all(accumulators[name]["selected"] for name in (
        "banker", "2_odds", "5_odds", "10_odds",
    ))


def test_available_now_final_portfolio_fails_closed_for_duplicate_fixture():
    rollover = {"games": [_available_now_game("A", "under_3_5")]}
    accumulators = {
        "banker": {"selected": True, "games": [_available_now_game("B")]},
        # It is a different market, proving fixture exposure rather than only
        # exact-selection exposure protects the action surface.
        "2_odds": {"selected": True, "games": [_available_now_game("B", "home_win")]},
        "5_odds": {"selected": True, "games": [_available_now_game("C")]},
        "10_odds": {"selected": True, "games": [_available_now_game("D")]},
    }

    portfolio = daily_feed._validate_bookable_now_portfolio(accumulators, rollover)

    assert accumulators["banker"]["selected"] is True
    assert accumulators["2_odds"]["selected"] is False
    assert accumulators["2_odds"]["games"] == []
    assert portfolio["withheld_products"] == [{
        "product": "2_odds",
        "duplicate_selection_ids": [],
        "duplicate_fixture_ids": ["B"],
    }]
    # The API exposes only the retained portfolio, so consumers can rely on
    # zero final overlap rather than interpreting an attempted duplicate.
    assert portfolio["portfolio_validation"]["valid"] is True
    assert portfolio["portfolio_validation"]["fixture_overlap_count"] == 0


def test_over_1_5_never_reuses_any_official_portfolio_fixture(monkeypatch):
    """October 8 regression: Banker and Over 1.5 shared the same selection.

    The single over market may appear on the model board, but it must not
    become a second official product after another category has claimed it.
    """
    target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    kickoff = f"{target_date}T18:00:00Z"
    picks = [_pick(i, kickoff) for i in range(40)]
    # Make fixture 0 an unambiguous safe Banker AND an Over 1.5 candidate.
    top = picks[0]
    top.update(confidence=.86, raw_confidence=.86, ml_confidence=.84)
    top["trust"].update(
        evidence_adjusted_probability=.86,
        lower_reliability_bound=.85,
        evidence_strength=.95,
    )
    monkeypatch.setattr(daily_feed, "_build_rollover", lambda *_, **kw: {
        "selected": False, "games": [], "chain": [], "chain_length": 0,
    })

    result = daily_feed.build_daily_accumulators(preview={
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_wat_date": target_date,
        "picks": picks,
        "fixtures": [p["_fixture"] for p in picks],
    })
    accumulators = result["accumulators"]
    banker_ids = {g["match_id"] for g in accumulators["banker"]["games"]}
    assert top["match_id"] in banker_ids
    all_ids = []
    for tier in ("rollover", "banker", "2_odds", "5_odds", "10_odds", "over_1_5"):
        all_ids.extend(g["match_id"] for g in accumulators[tier].get("games", []))

    assert len(all_ids) == len(set(all_ids))
    assert not banker_ids.intersection(
        {g["match_id"] for g in accumulators["over_1_5"].get("games", [])}
    )
