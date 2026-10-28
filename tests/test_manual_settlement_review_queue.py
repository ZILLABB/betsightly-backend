"""Evidence review displays unresolved receipts but never grades anything."""
import json
from datetime import datetime, timezone

from leagues.manual_settlement_review import build_review_queue
from growth.api import router


def _rows():
    return [
        ("2026-10-25", "5_odds", json.dumps({
            "booking": {"share_code": "DO_NOT_EXPOSE"},
            "games": [
                {"status": "pending", "sportybet_event_id": "sr:match:123",
                 "home_team": "Club A", "away_team": "Club B",
                 "kickoff": "2026-10-25T14:00:00Z", "league": "Premier League",
                 "sportybet_country": "Singapore",
                 "sportybet_tournament_id": "sr:tournament:99999",
                 "settlement_pending_reason": "FINAL_SCORE_UNVERIFIED"},
                {"status": "won", "sportybet_event_id": "sr:match:456",
                 "home_team": "A", "away_team": "B"},
            ],
        })),
        ("2026-10-23", "2_odds", json.dumps({"games": [
            {"status": "pending", "sportybet_event_id": "sr:match:500",
             "home_team": "FC Den Bosch", "away_team": "MVV Maastricht",
             "kickoff": "2026-10-23T18:00:00Z", "league": "Eerste Divisie"},
        ]})),
    ]


def test_queue_preserves_country_origin_and_no_sensitive_booking_code():
    rows = _rows()
    before = json.dumps(rows)
    output = build_review_queue(
        rows, limit=1, now=datetime(2026, 10, 28, 9, tzinfo=timezone.utc))
    assert output["total_pending_legs"] == 2
    assert output["returned"] == 1
    assert output["unique_events"] == 2
    assert output["overdue_48h"] == 2
    assert output["legs"][0]["review_category"] == "country_unknown"
    assert output["review_categories"] == {
        "country_unknown": 1, "source_unsupported": 1}
    assert json.dumps(rows) == before
    assert "DO_NOT_EXPOSE" not in json.dumps(output)


def test_review_queue_country_mapping_and_registered_provider():
    result = build_review_queue([
        ("2026-10-26", "5_odds", {"games": [{
            "status": "pending", "sportybet_event_id": "sr:match:123",
            "home_team": "Liverpool", "away_team": "Brighton",
            "kickoff": "2026-10-26T17:00:00Z",
            "league": "English Premier League",
            "competition_country": "England",
            "settlement_source_candidates": ["espn"]}]})
    ], now=datetime(2026, 10, 28, 9, tzinfo=timezone.utc))
    row = result["legs"][0]
    assert row["country"] == "England"
    assert row["country_basis"] == "registry"
    assert row["review_category"] == "source_recheck"


def test_review_route_requires_admin_guard():
    route = next(r for r in router.routes
                 if getattr(r, "path", "") == "/manual-tiers/settlement-review")
    from growth.admin_auth import require_admin
    assert require_admin in [dep.call for dep in route.dependant.dependencies]
    assert "GET" in route.methods
