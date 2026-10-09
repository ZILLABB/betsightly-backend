"""A stale prepared board can be diagnosed without running prediction ML."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts import probe_staging_failed_espn_leagues as probe_script


def today_wat():
    return datetime.now(timezone(timedelta(hours=1))).date().isoformat()


def test_saved_board_failures_remain_inspectable_after_ttl(monkeypatch):
    from leagues import prepared_board_store
    monkeypatch.setattr(prepared_board_store, "load_entries", lambda: [
        {"saved_at": "2026-10-08T18:00:00+00:00", "entry": {
            "metadata": {"provider": {"failed_leagues": ["alg.1"]}}
        }},
        {"saved_at": "2026-10-09T00:00:00+00:00", "entry": {
            "metadata": {
                "decision_snapshot_id": "new-staging",
                "provider": {"failed_leagues": ["kor.1", "alg.1", "alg.1"]},
            }
        }},
    ])
    failures, snapshot = probe_script.failed_from_saved_snapshot()
    assert failures == ["alg.1", "kor.1"]
    assert snapshot == "new-staging"


def test_failed_league_probe_cannot_write_or_rebuild(monkeypatch):
    from leagues import espn_source
    monkeypatch.setattr(probe_script, "preflight", lambda: "betsightly_db_staging")
    observations = {}

    def fetch(slug, month):
        observations[slug] = month
        return [] if slug == "alg.1" else [{"event_id": "123"}]

    monkeypatch.setattr(espn_source, "_fetch_league", fetch)
    monkeypatch.setattr(espn_source, "fetch_health", lambda: {
        "alg.1": {"request_succeeded": False, "error": "HTTP 404"},
        "kor.1": {"request_succeeded": True, "provider_active": True},
    })
    report = probe_script.probe(today_wat(), slugs=["kor.1", "alg.1"])
    assert report["database"] == "betsightly_db_staging"
    assert report["requested_failed_leagues"] == 2
    assert report["states"]["UNAVAILABLE"] == 1
    assert report["states"]["REACHABLE_WITH_FIXTURES"] == 1
    assert report["per_league"][0]["http_or_transport_error"] == "HTTP 404"
    assert set(observations) == {"alg.1", "kor.1"}
    assert report["source_diagnostic_only"] is True
    assert report["prepared_board_refreshed"] is False
    assert report["publishing_changed"] is False
    assert report["booking_codes_created"] is False


def test_refuses_unknown_provider_slugs_without_requests(monkeypatch):
    from leagues import espn_source
    monkeypatch.setattr(probe_script, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        espn_source, "_fetch_league",
        lambda *args: pytest.fail("unexpected network access"),
    )
    with pytest.raises(ValueError, match="Unregistered"):
        probe_script.probe(today_wat(), slugs=["../../../admin"])


def test_staging_preflight_runs_before_saved_snapshot_or_network(monkeypatch):
    monkeypatch.setattr(probe_script, "preflight", lambda: (_ for _ in ())
                        .throw(RuntimeError("wrong database")))
    monkeypatch.setattr(probe_script, "failed_from_saved_snapshot",
                        lambda: pytest.fail("must fail before cache read"))
    with pytest.raises(RuntimeError, match="wrong database"):
        probe_script.probe(today_wat())
