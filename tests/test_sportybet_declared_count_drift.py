"""SportyBet declared-page count can drift during a live scan."""
from leagues import sportybet


def _mock_fetch(monkeypatch, *, declared_total, ids):
    persisted = []
    monkeypatch.setattr(sportybet, "_db_get", lambda key: None)
    monkeypatch.setattr(sportybet, "_db_set", lambda key, value: persisted.append(value))
    monkeypatch.setattr(
        sportybet, "_get_json",
        lambda url: {
            "data": {
                "totalNum": declared_total,
                "tournaments": [{
                    "name": "Test league",
                    "events": [{"id": value} for value in ids],
                }],
            },
        },
    )
    monkeypatch.setattr(
        sportybet, "_parse_event",
        lambda event: {
            "event_id": event["id"],
            "home_team": "Home " + event["id"],
            "away_team": "Away " + event["id"],
            "kickoff_ms": 1791554400000,
            "prices": {"home_win": 1.5},
        },
    )
    monkeypatch.setattr(
        sportybet, "_tournament_identity_metadata",
        lambda tournament: {},
    )
    board = sportybet.fetch_board(max_pages=1, force=True)
    return board, persisted


def test_more_real_events_than_declared_does_not_drop_real_fixture(monkeypatch):
    board, saved = _mock_fetch(monkeypatch, declared_total=1, ids=["a", "b"])
    meta = board["__meta__"]
    assert meta["declared_total"] == 1
    assert meta["unique_indexed_fixtures"] == 2
    assert meta["declared_count_difference"] == 1
    assert meta["declared_count_changed_during_scan_possible"] is True
    assert meta["is_complete"] is True
    assert len(list(sportybet._board_entries(board))) == 2
    assert saved[0]["metadata"]["declared_count_difference"] == 1


def test_fewer_events_than_declared_remains_incomplete(monkeypatch):
    board, _ = _mock_fetch(monkeypatch, declared_total=3, ids=["a", "b"])
    assert board["__meta__"]["declared_count_difference"] == -1
    assert board["__meta__"]["is_complete"] is False
