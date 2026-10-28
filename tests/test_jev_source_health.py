from datetime import datetime, timezone
from scripts.jev_source_health import probe_sources

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def test_keyless_health_check_is_observational_only():
    calls = []
    def fake(league, *, environ, now):
        calls.append((league, environ["BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED"]))
        return {"status": "ok", "fixtures": [{"source_id": "openligadb"}],
                "evidence": [], "auto_discovered_group": 8,
                "attribution": "OpenLigaDB ODbL"}
    result = probe_sources(now=NOW, fetcher=fake)
    assert result["status"] == "ok"
    assert [p[0] for p in calls] == ["bl1", "bl2"]
    assert result["jev_calls_made"] == 0
    assert result["official_predictions_changed"] is False


def test_failures_are_reported_not_silently_accepted():
    def bad(league, **kwargs):
        if league == "bl2":
            raise TimeoutError("source timeout")
        return {"status": "ok", "fixtures": []}
    result = probe_sources(now=NOW, fetcher=bad)
    assert result["status"] == "degraded"
    assert result["checks"][1]["reason"] == "TimeoutError"
    assert result["independent_settlement_verified"] is False


def test_empty_provider_board_is_reported_as_degraded():
    def empty(league, **kwargs):
        return {"status": "ok", "fixtures": [], "evidence": []}
    result = probe_sources(now=NOW, fetcher=empty)
    assert result["status"] == "degraded"
    assert all(item["status"] == "empty" for item in result["checks"])
