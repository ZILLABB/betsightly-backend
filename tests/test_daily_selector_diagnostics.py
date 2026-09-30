from scripts.diagnose_daily_selector import diagnose


def test_exact_offline_feasibility_agrees_with_reachable_synthetic_10x():
    groups = ("goals", "double_chance", "dnb")
    picks = [{
        "match_id": f"fixture-{index}",
        "market": "over_1_5" if index % 3 == 0 else
                  "home_or_draw" if index % 3 == 1 else "dnb_home",
        "market_group": groups[index % 3],
        "confidence": .75, "odds": 1.35,
        "odds_are_real": True, "bookable": True,
    } for index in range(12)]
    report = diagnose(picks)
    assert report["full_pool"]["feasible"] is True
    assert report["bounded_pool"]["feasible"] is True
    assert report["production_odds"] >= 8
    assert len(report["full_pool"]["legs"]) <= 10
