"""Anonymous Builder win alerts are privacy-scoped and never claim bets."""
from datetime import datetime, timezone

from leagues import visitor_notifications as notice


def test_no_private_lookup_without_high_entropy_browser_uuid(monkeypatch):
    from database import engine
    def no_db():
        raise AssertionError("Never query for a missing/weak visitor credential")
    monkeypatch.setattr(engine, "connect", no_db)
    for ident in (None, "", "anon_123", "anon_" + "x"*36, "a@example.com"):
        assert notice.winning_notifications(ident)["notifications"] == []


def test_query_exactly_matches_complete_ticket_and_scopes_anonymous_visitor():
    query = str(notice._WIN_SQL)
    assert "h.anonymous_id = :visitor" in query
    assert "t.selected = w.selected" in query
    assert "p.final_status = 'won'" in query
    assert "h.booking_validated IS TRUE" in query
    assert "ORDER BY s.selection_fingerprint::text" in query
    assert "JOIN user_ticket_selections" in query
    assert "FROM builder_predictions" in query


def test_personal_winning_notification_does_not_mention_or_claim_real_wager(monkeypatch):
    import database
    identity = "anon_2f13d9a5-cc88-4aa8-a5e0-1e05a037df60"

    class Connection:
        def execute(self, query, params):
            assert params["visitor"] == identity
            assert params["limit"] <= 30
            class Rows:
                def mappings(self):
                    return self
                def all(self):
                    return [{
                        "ticket_id": "test-ticket-only",
                        "generated_at": datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
                        "settled_at": datetime(2026, 10, 13, 21, tzinfo=timezone.utc),
                        "prediction_odds": 10.25, "leg_count": 12,
                    }]
            return Rows()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None

    class Engine:
        def connect(self):
            return Connection()
    monkeypatch.setattr(database, "engine", Engine())
    report = notice.winning_notifications(identity)
    assert report["status"] == "success"
    assert report["predictions_only"] is True
    assert report["notifications"] == [{
        "ticket_id": "test-ticket-only",
        "generated_at": "2026-10-13T07:00:00+00:00",
        "won_at": "2026-10-13T21:00:00+00:00",
        "prediction_odds": 10.25,
        "leg_count": 12,
        "status": "won",
        "wager_confirmed": False,
    }]
    assert identity not in str(report)
    assert "anonymous_id" not in str(report)


def test_private_lookup_fails_closed_if_database_unavailable(monkeypatch):
    import database
    class Engine:
        def connect(self):
            raise RuntimeError("database unavailable")
    monkeypatch.setattr(database, "engine", Engine())
    value = notice.winning_notifications(
        "anon_2f13d9a5-cc88-4aa8-a5e0-1e05a037df60",
    )
    assert value["status"] == "unavailable"
    assert value["notifications"] == []
