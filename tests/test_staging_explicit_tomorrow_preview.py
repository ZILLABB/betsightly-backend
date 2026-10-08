"""Exact WAT date in staging preview cannot roll into the wrong day."""
from datetime import datetime, timezone

import pytest

from scripts import preview_staging_official_card as preview


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 8, 22, 0, tzinfo=timezone.utc)


def test_explicit_october_ninth_staging_preview_is_read_only_and_dated(monkeypatch):
    from leagues import daily_feed, engine

    captured = []
    monkeypatch.setattr(preview, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(preview, "datetime", FixedDatetime)
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: (
            [{"match_id": "match-1"}], [{"match_id": "match-1"}],
            {"ready": True, "stale": False, "board_snapshot_id": "sha123",
             "age_seconds": 1800, "complete": False, "degraded": True},
        ),
    )

    def read_only_card(**kwargs):
        captured.append(kwargs)
        return {
            "locked": False,
            "fixture_target_date": "2026-10-09",
            "accumulators": {
                "2_odds": {
                    "selected": True,
                    "games": [{
                        "match_id": "match-1",
                        "home_team": "Home FC",
                        "away_team": "Away FC",
                        "market": "over_1_5",
                        "odds": 1.45,
                        "confidence": .72,
                        "kickoff": "2026-10-09T16:00:00Z",
                    }],
                    "total_odds": 1.45,
                },
            },
        }

    monkeypatch.setattr(daily_feed, "build_daily_accumulators", read_only_card)
    result = preview.simulate(target_date_wat="2026-10-09")
    assert result["target_wat_date"] == "2026-10-09"
    assert result["requested_date_matched"] is True
    assert result["official_publication"] is False
    assert result["booking_codes_created"] is False
    assert result["official_product_preview"]["2_odds"]["proposed_games"][0]["market"] == "over_1_5"
    assert captured[0]["preview"]["target_wat_date"] == "2026-10-09"
    assert len(captured) == 1


@pytest.mark.parametrize("bad", ["2026-10-07", "2026-10-16", "tomorrow"])
def test_explicit_preview_rejects_out_of_window_or_malformed_date(monkeypatch, bad):
    from leagues import engine

    monkeypatch.setattr(preview, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(preview, "datetime", FixedDatetime)
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: (
            [{"match_id": "1"}], [{"match_id": "1"}],
            {"ready": True, "stale": False, "board_snapshot_id": "sha"},
        ),
    )
    with pytest.raises(ValueError, match="Target date"):
        preview.simulate(target_date_wat=bad)
