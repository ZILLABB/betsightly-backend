from scripts import backfill_phase8_missing_espn_history as backfill


def test_backfill_uses_exact_missing_target_mapping():
    assert backfill.MISSING_TARGETS == {
        265: "chi.1",
        292: "kor.1",
        307: "sau.1",
    }


def test_backfill_normalizes_espn_rows(monkeypatch):
    monkeypatch.setattr(
        backfill,
        "finished_matches",
        lambda slug, start, end: [
            {
                "id": "abc",
                "date": "2025-01-02",
                "home": "Alpha",
                "away": "Beta",
                "hs": 2,
                "as": 1,
            }
        ],
    )
    rows, report = backfill.fetch_rows(
        [265],
        "2025-01-01",
        "2025-01-31",
    )
    assert len(rows) == 1
    assert rows[0]["league_id"] == 265
    assert rows[0]["provider"] == "ESPN"
    assert rows[0]["provider_event_id"] == "abc"
    assert rows[0]["home_score"] == 2
    assert rows[0]["away_score"] == 1
