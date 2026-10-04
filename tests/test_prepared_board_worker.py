from scripts import prepared_board_worker as worker


def test_prepared_board_worker_only_requests_noninteractive_prewarm(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "leagues.engine.prepared_board_status",
        lambda days_ahead=7: {
            "ready": False,
            "stale": True,
            "age_seconds": 9999,
            "fixture_count": 0,
            "board_snapshot_id": None,
        },
    )

    monkeypatch.setattr(
        "leagues.engine.start_history_prewarm",
        lambda request_triggered=False: (
            calls.append(request_triggered) or True
        ),
    )

    result = worker.run_once()

    assert calls == [False]
    assert result["refresh_requested"] is True
    assert result["ready_before"] is False
    assert result["stale_before"] is True
