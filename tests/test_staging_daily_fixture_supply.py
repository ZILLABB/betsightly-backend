"""Audit the daily football supply gap without permitting false predictions."""
from datetime import datetime, timezone

from scripts.audit_staging_daily_fixture_supply import inventory_for_day


def _event(event_id, tid, cid, competition, *, hour=18, squad="", priced=True):
    start = datetime(2026, 10, 9, hour, tzinfo=timezone.utc)
    return {
        "event_id": event_id,
        "kickoff_ms": int(start.timestamp() * 1000),
        "competition": competition,
        "sportybet_tournament_id": tid,
        "sportybet_category_id": cid,
        "sportybet_category": "Test",
        "home_team": "Home",
        "away_team": "Away",
        "home_squad": squad,
        "away_squad": "",
        "prices": {"over_1_5": 1.45} if priced else {},
    }


def test_daily_supply_counts_safe_extra_leagues_but_not_algerian_ligue_2():
    board = {
        "matched": [_event("match-1", "sr:tournament:182", "sr:category:7", "Ligue 2")],
        "added": [_event("match-2", "sr:tournament:955", "sr:category:310", "Saudi Pro League")],
        "algeria": [_event("match-3", "sr:tournament:14321", "sr:category:304", "Ligue 2")],
        "youth": [_event("match-4", "sr:tournament:196", "sr:category:52", "J1 League", squad="u19")],
        "unpriced": [_event("match-5", "sr:tournament:410", "sr:category:291", "K-League 1", priced=False)],
        "tomorrow": [_event("match-6", "sr:tournament:649", "sr:category:99", "Chinese Super League", hour=23)],
    }
    # 23:00 UTC is already October 10 WAT and must not inflate Oct 9.
    fixtures = [{
        "match_id": "espn-1",
        "commence_time": "2026-10-09T18:00:00Z",
        "odds": {"sportybet_event_id": "match-1"},
    }]
    result = inventory_for_day(board, fixtures, "2026-10-09")
    assert result["modelled_espn_fixtures"] == 1
    assert result["sportybet_fixture_count"] == 5
    assert result["already_modelled_with_exact_sportybet_event_id"] == 1
    assert result["sportybet_only_fixture_count"] == 4
    assert result["sportybet_only_unmapped_competition"] == 1
    assert result["sportybet_only_exact_competition_map"] == 3
    assert result["sportybet_only_mapped_senior_priced"] == 1
    assert result["sportybet_only_mapped_unsupported_squad"] == 1
    assert result["sportybet_only_mapped_unpriced"] == 1
    assert result["potential_history_ready_leagues"] == {"sau.1": 1}
