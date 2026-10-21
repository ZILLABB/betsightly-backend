"""Read-only market readiness without inventing live training or odds."""
import pytest

from growth.market_readiness import _count_readonly, market_readiness_snapshot


def test_product_inventory_and_rejection_counts_are_not_reinterpreted():
    card = {
        "banker": {"selected": True, "games": [{"match_id": "one"}], "total_odds": 1.35},
        "2_odds": {"selected": True, "games": [{"match_id": "a"}, {"match_id": "b"}], "total_odds": 1.92},
        "5_odds": {"selected": False, "games": [], "total_odds": 0},
        "10_odds": {"selected": False, "games": [], "total_odds": 0},
        "over_1_5": {"selected": False, "games": [], "total_odds": 0},
        "_portfolio": {
            "tier_supply_diagnostics": {
                "qualified_fixtures": 6, "qualified_selections": 7,
                "reserved_fixtures": 5, "remaining_qualified_fixtures": 1,
            },
            "publication_policy": {"rejections": {"official": {
                "NEGATIVE_MODEL_VALUE": 88,
                "MARKET_NOT_TRUSTED": 39,
                "INSUFFICIENT_SETTLED_EVIDENCE": 48,
            }}},
        },
    }
    def replay(market):
        return {"n": 1000, "calibration_error": 0.0035,
                "bookmaker_n": 0, "skill_vs_bookmaker": None} if market == "over_1_5" else None

    report = market_readiness_snapshot(
        day="2026-10-21", card=card, replay_lookup=replay,
        include_db_telemetry=False,
    )
    assert report["date"] == "2026-10-21"
    assert report["qualified_fixtures"] == 6
    assert report["remaining_qualified_fixtures"] == 1
    assert report["products"]["5_odds"]["selected"] is False
    assert report["products"]["2_odds"]["leg_count"] == 2
    assert report["rejections"]["NEGATIVE_MODEL_VALUE"] == 88
    over_zero = next(x for x in report["markets"] if x["market"] == "over_0_5")
    over_one = next(x for x in report["markets"] if x["market"] == "over_1_5")
    assert over_zero["historical_replay_missing"] is True
    assert over_zero["historical_replay_observations"] is None
    assert over_one["historical_replay_observations"] == 1000
    assert over_one["historical_replay_is_not_training"] is True
    assert over_one["historical_bookmaker_n"] == 0
    assert report["read_only"] is True


def test_missing_publication_does_not_manufacture_market_readiness():
    report = market_readiness_snapshot(
        day="2026-10-21", card={},
        replay_lookup=lambda _: None, include_db_telemetry=False,
    )
    assert report["published_card_available"] is False
    assert report["qualified_fixtures"] is None
    assert all(not value["selected"] for value in report["products"].values())
    assert all(row["historical_replay_missing"] for row in report["markets"])


def test_unknown_telemetry_table_is_rejected_before_sql():
    with pytest.raises(ValueError, match="Unsupported telemetry table"):
        _count_readonly("model_training_runs; DROP TABLE users")


def test_admin_market_status_is_protected_and_read_only():
    from growth.admin_ui import ADMIN_HTML, ADMIN_JS
    from growth.api import growth_market_readiness
    import inspect
    from pathlib import Path

    src = Path(inspect.getsourcefile(growth_market_readiness)).read_text()
    assert '@router.get("/market-readiness", dependencies=[Depends(require_admin)])' in src
    assert 'id="marketReadiness"' in ADMIN_HTML
    assert "loadMarketReadiness()" in ADMIN_JS
    assert "NEGATIVE_MODEL_VALUE" not in ADMIN_JS  # sourced, not hardcoded
    assert "Refreshing market evidence" in ADMIN_JS
