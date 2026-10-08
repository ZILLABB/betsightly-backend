"""Staging preview supply diagnostics must stay read-only and date-scoped."""
from datetime import datetime, timezone

from scripts.preview_staging_official_card import diagnose_supply


def _pick(match_id, kickoff, *, confidence=.8, bookable=True, real=True):
    return {
        "match_id": match_id,
        "market": "over_1_5",
        "market_group": "over_1_5",
        "prediction": "Over 1.5",
        "odds": 1.4,
        "confidence": confidence,
        "raw_confidence": confidence,
        "bookable": bookable,
        "odds_are_real": real,
        "safe_tier_eligible": True,
        "market_floor_eligible": True,
        "market_trust_state": "TRUSTED",
        "risk_adjusted_return": 1.02,
        "_fixture": {
            "match_id": match_id,
            "commence_time": kickoff,
            "home": {"name": f"Home {match_id}"},
            "away": {"name": f"Away {match_id}"},
        },
    }


def test_supply_audit_is_wat_date_scoped_and_counts_multiple_reasons(monkeypatch):
    # Separate the diagnostic contract from heuristic fixture ranking.
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda picks, include_all_eligible=False: list(picks),
    )
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    picks = [
        _pick("good", "2026-10-09T17:00:00Z"),
        _pick("bad", "2026-10-09T18:00:00Z", bookable=False, real=False),
        _pick("next", "2026-10-10T17:00:00Z"),
        # 23:30 UTC is already October 10 in Nigeria.
        _pick("wat-next", "2026-10-09T23:30:00Z"),
    ]
    result = diagnose_supply(picks, "2026-10-09", now)
    assert result["forecast_legs_on_target_day"] == 2
    assert result["forecast_unique_fixtures_on_target_day"] == 2
    assert result["priced_bookable_forecasts"] == 1
    two = result["products"]["2_odds"]
    assert two["approved_unique_fixtures"] == 1
    assert two["rejection_reasons"]["NOT_EXACTLY_BOOKABLE"] == 1
    assert two["rejection_reasons"]["ESTIMATED_PRICE"] == 1


def test_supply_audit_filters_started_matches(monkeypatch):
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda picks, include_all_eligible=False: list(picks),
    )
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    picks = [_pick("started", "2026-10-09T10:00:00Z"),
             _pick("later", "2026-10-09T20:00:00Z")]
    result = diagnose_supply(picks, "2026-10-09", now)
    assert result["forecast_unique_fixtures_on_target_day"] == 1
    assert result["products"]["2_odds"]["approved_unique_fixtures"] == 1
