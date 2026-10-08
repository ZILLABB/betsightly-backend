"""Regression coverage for quality-aware, read-only Next Available inventory."""
from datetime import datetime, timezone

from leagues import next_available


def _candidate(
    fixture_id: str, date: str, *,
    eligible: bool = True,
    market: str = "over_1_5",
):
    confidence = .79
    return {
        "match_id": fixture_id,
        "market": market,
        "market_group": "goals",
        "prediction": "Over 1.5 Goals",
        "confidence": confidence,
        "raw_confidence": confidence,
        "odds": 1.50 if eligible else 1.09,
        "odds_are_real": True,
        "odds_provider": "SportyBet",
        "expected_value": .09 if eligible else -.12,
        "edge": .09 if eligible else -.12,
        "bookable": True,
        "market_floor_eligible": True,
        "safe_tier_eligible": True,
        "market_trust_state": "TRUSTED",
        "market_margin": .04,
        "trust": {
            "accepted": True,
            "trust_grade": "A",
            "evidence_strength": .9,
            "evidence_adjusted_probability": confidence,
            "lower_reliability_bound": .76,
        },
        "_fixture": {
            "match_id": fixture_id,
            "commence_time": f"{date}T18:00:00Z",
            "home": {"name": f"Home {fixture_id}"},
            "away": {"name": f"Away {fixture_id}"},
            "league": "Test League",
            "league_slug": "eng.1",
            "competition_type": "LEAGUE",
            "venue": {},
        },
        "_model": {
            "expected_goals": {"home": 1.5, "away": 1.1, "total": 2.6},
            "probabilities": {"draw": .25},
            "has_market": True,
        },
    }


def test_next_available_skips_raw_but_negative_value_day(monkeypatch):
    # Isolate the exact publication gate; ranking is exercised in separate
    # fixture-ranker tests. False positives cannot inflate approved supply.
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda p: p,
    )
    picks = [
        _candidate(f"thin-{i}", "2026-10-09", eligible=False)
        for i in range(6)
    ] + [
        _candidate(f"good-{i}", "2026-10-10")
        for i in range(4)
    ]
    result = next_available.next_available_quality_board(
        picks, now=datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc),
        min_unique_fixtures=3,
    )
    assert result["available"] is True
    assert result["publication_date_wat"] == "2026-10-08"
    assert result["next_available"]["fixture_target_date"] == "2026-10-10"
    assert result["evaluated_dates"][0]["raw_fixture_count"] == 6
    assert result["evaluated_dates"][0]["qualified_unique_fixture_count"] == 0
    assert result["evaluated_dates"][0]["rejection_reasons"]["NEGATIVE_MODEL_VALUE"] == 6
    assert result["evaluated_dates"][1]["qualified_unique_fixture_count"] == 4
    assert result["preview_only"] is True
    assert result["official_publication"] is False
    assert result["actionable"] is False
    assert result["bookable_code_verified"] is False
    assert all("booking" not in g for g in result["next_available"]["candidates"])


def test_next_available_counts_unique_fixtures_and_never_claims_unsafe_day(monkeypatch):
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda p: p,
    )
    picks = [_candidate("same", "2026-10-09") for _ in range(6)]
    report = next_available.next_available_quality_board(
        picks, now=datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc),
        horizon_days=2,
        min_unique_fixtures=2,
    )
    assert report["available"] is False
    assert report["next_available"] is None
    assert report["evaluated_dates"][0]["qualified_selection_count"] == 6
    assert report["evaluated_dates"][0]["qualified_unique_fixture_count"] == 1


def test_next_available_only_uses_future_wat_dates_and_past_kickoffs_are_skipped(monkeypatch):
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda p: p,
    )
    picks = [_candidate(f"future-{i}", "2026-10-10") for i in range(3)]
    picks.append(_candidate("today", "2026-10-08"))
    report = next_available.next_available_quality_board(
        picks, now=datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc),
        horizon_days=2,
        min_unique_fixtures=3,
    )
    assert report["available"] is True
    assert report["next_available"]["fixture_target_date"] == "2026-10-10"
    assert all(g["match_id"] != "today" for g in report["next_available"]["candidates"])


def test_next_available_rejects_stale_prepared_board(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from leagues import api as league_api

    monkeypatch.setattr(
        league_api, "_public_prepared_board",
        lambda horizon: (
            [{"match_id": "old"}],
            [{"match_id": "old"}],
            {"ready": True, "stale": True, "age_seconds": 5400},
        ),
    )
    monkeypatch.setattr(
        "leagues.next_available.next_available_quality_board",
        lambda *_: pytest.fail("stale market candidates must not be served"),
    )
    with pytest.raises(HTTPException) as error:
        league_api.get_next_available()
    assert error.value.status_code == 503
    assert error.value.detail["reason"] == "prepared_board_stale"
    assert error.value.detail["retryable"] is True
