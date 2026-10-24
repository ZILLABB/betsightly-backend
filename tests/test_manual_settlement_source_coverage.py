"""Guard the root causes of manual-scores staying unverified for weeks.

All examples are synthetic, with no calls to the sportsbook or score sites.
"""
from datetime import datetime, timezone

from leagues.editorial_settlement import grade_manual_slip
from leagues.results_checker import (
    _known_score_slugs, _lookup_settlement_score, _normalize_name,
)


def test_verified_competition_names_are_resolved_without_manual_slug():
    rows = [
        {"league": "UEFA Champions League"},
        {"league": "UEFA Europa League"},
        {"league": "English Championship"},
    ]
    slugs = _known_score_slugs(rows)
    assert slugs is not None
    assert {"uefa.champions", "uefa.europa", "eng.2"} <= slugs


def test_ambiguous_or_unsupported_manual_league_not_guessed():
    assert _known_score_slugs([{"league": "Premier League"},
                               {"league": "Unknown Country Youth Cup"}]) is None


def test_manual_receipt_team_alias_settles_only_matching_date_and_orientation():
    assert _normalize_name("Man Utd") == _normalize_name("Manchester United")
    now = datetime(2026, 10, 24, 2, tzinfo=timezone.utc)
    leg = {
        "home_team": "Man Utd", "away_team": "Liverpool",
        "kickoff": "2026-10-23T19:00:00Z", "market": "over_1_5",
        "status": "pending",
    }
    record = {"games": [leg], "booking": {"share_code": "IMMUTABLE"},
              "result_status": "pending"}
    scores = {
        "manchester united|liverpool|2026-10-23": {
            "completed": True, "home_score": 2, "away_score": 1,
            "provider": "espn", "provider_event_id": "123",
            "score_90": {"home": 2, "away": 1}, "match_status": "FT",
        }
    }
    result = grade_manual_slip(record, scores, now=now)
    assert result["result_status"] == "won"
    assert result["games"][0]["status"] == "won"
    assert result["booking"] == record["booking"]
    assert grade_manual_slip(record, {
        "manchester united|liverpool|2026-10-22": list(scores.values())[0]
    }, now=now)["result_status"] == "pending"
    assert _lookup_settlement_score(scores, "Liverpool", "Man Utd",
                                    "2026-10-23") is None


def test_unknown_manual_market_stays_pending_even_with_verified_final():
    now = datetime(2026, 10, 24, 2, tzinfo=timezone.utc)
    record = {"games": [{
        "home_team": "Man Utd", "away_team": "Liverpool",
        "kickoff": "2026-10-23T19:00:00Z", "market": "unknown_special",
    }]}
    score = {"manchester united|liverpool|2026-10-23": {
        "home_score": 2, "away_score": 1, "provider": "espn",
        "provider_event_id": "123",
    }}
    graded = grade_manual_slip(record, score, now=now)
    assert graded["result_status"] == "pending"
    assert graded["games"][0]["settlement_pending_reason"] == "UNSUPPORTED_MARKET"
