"""Staging official-card preview never publishes and fails closed."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts import preview_staging_official_card as preview


def _data(monkeypatch, *, stale=False, duplicate=False):
    from leagues import daily_feed, engine

    monkeypatch.setattr(preview, "preflight", lambda: "betsightly_db_staging")
    picks = [{"match_id": "a", "_fixture": {"commence_time": "2099-01-01T21:00:00Z"}}]
    fixtures = [picks[0]["_fixture"]]
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: (
        picks, fixtures,
        {"ready": True, "stale": stale, "complete": False, "degraded": True,
         "age_seconds": 24, "board_snapshot_id": "sha"},
    ))

    def fake_build(*, preview):
        assert preview["picks"] is picks
        assert preview["fixtures"] is fixtures
        assert preview["target_wat_date"] == (
            (datetime.now(timezone.utc) + timedelta(hours=1)).date()
            + timedelta(days=1)
        ).isoformat()
        return {
            "locked": False,
            "fixture_target_date": preview["target_wat_date"],
            "accumulators": {
                "banker": {
                    "selected": True, "games": [
                        {"match_id": "a"},
                    ], "total_odds": 1.38,
                },
                "2_odds": {
                    "selected": duplicate, "games": [
                        {"match_id": "a"},
                    ] if duplicate else [], "total_odds": 2.1,
                },
            },
            "publication_policy": {"version": "test"},
        }

    monkeypatch.setattr(daily_feed, "build_daily_accumulators", fake_build)


def test_preview_reports_policy_without_publication(monkeypatch):
    _data(monkeypatch)
    result = preview.simulate()
    assert result["database"] == "betsightly_db_staging"
    assert result["preview_only"]
    assert result["official_publication"] is False
    assert result["locked"] is False
    assert result["booking_codes_created"] is False
    assert result["model_candidate_picks"] == 1
    assert result["official_product_preview"]["banker"]["legs"] == 1
    assert result["official_product_preview"]["10_odds"]["selected"] is False
    assert result["duplicate_fixture_count"] == 0


def test_preview_refuses_stale_prepared_board(monkeypatch):
    _data(monkeypatch, stale=True)
    with pytest.raises(RuntimeError, match="missing or stale"):
        preview.simulate()


def test_preview_refuses_duplicate_official_fixture(monkeypatch):
    _data(monkeypatch, duplicate=True)
    with pytest.raises(RuntimeError, match="Duplicate fixture"):
        preview.simulate()
