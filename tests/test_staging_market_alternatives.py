"""No side effects: audit alternative markets under the same quality gates."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts import audit_staging_market_alternatives as alternatives


def _fixtures():
    day = (datetime.now(timezone.utc) + timedelta(hours=1)).date() + timedelta(days=1)
    kickoff = f"{day.isoformat()}T18:00:00Z"
    return [
        {"match_id": "a", "market": "over_1_5", "allowed": False,
         "_fixture": {"commence_time": kickoff}},
        {"match_id": "a", "market": "home_or_draw", "allowed": True,
         "_fixture": {"commence_time": kickoff}},
        {"match_id": "b", "market": "over_1_5", "allowed": True,
         "_fixture": {"commence_time": kickoff}},
    ]


def test_all_active_alternatives_recover_same_fixture_other_market(monkeypatch):
    from leagues import fixture_ranker, publication_policy

    picks = _fixtures()

    def ranked(raw, *, include_all_eligible=False):
        if include_all_eligible:
            return list(raw)
        return [p for p in raw if p["market"] == "over_1_5"]

    def quality(raw, _product):
        return (
            [p for p in raw if p["allowed"]],
            [p for p in raw if not p["allowed"]],
        )

    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations", ranked
    )
    monkeypatch.setattr(
        publication_policy, "filter_official_candidates", quality
    )

    report = alternatives._report_day("2026-10-09", picks)
    five = report["products"]["5_odds"]
    assert report["raw_fixtures"] == 2
    assert report["ranked_two_candidate_count"] == 2
    assert report["all_active_candidate_count"] == 3
    assert five["baseline_qualified_unique"] == 1
    assert five["all_active_markets_qualified_unique"] == 2
    assert five["additional_qualified_fixtures"] == 1
    assert five["additional_qualified_market_mix"] == {"home_or_draw": 1}
    over = report["products"]["over_1_5"]
    assert over["additional_qualified_fixtures"] == 0


def test_full_audit_uses_existing_board_only(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(
        alternatives, "preflight", lambda: "betsightly_db_staging"
    )
    picks = _fixtures()
    monkeypatch.setattr(
        engine, "prepared_board", lambda days_ahead: (
            picks, [p["_fixture"] for p in picks],
            {"ready": True, "stale": False, "board_snapshot_id": "test",
             "degraded": True},
        )
    )
    monkeypatch.setattr(
        alternatives, "_report_day", lambda day, day_picks: {
            "fixture_date_wat": day,
            "raw_fixtures": 2,
            "raw_market_candidates": len(day_picks),
            "products": {
                product: {
                    "baseline_qualified_unique": 1,
                    "all_active_markets_qualified_unique": 2,
                    "additional_qualified_fixtures": 1,
                }
                for product in alternatives.PRODUCTS
            },
        },
    )
    summary = alternatives.audit()
    assert summary["database"] == "betsightly_db_staging"
    assert summary["mode"] == "READ_ONLY_STAGING_MARKET_ALTERNATIVES_AUDIT"
    assert summary["official_publication"] is False
    assert summary["booking_codes_created"] is False
    assert summary["quality_thresholds_changed"] is False
    assert summary["total_eligible_by_product"]["5_odds"][
        "additional_qualified_fixture_sum"
    ] == 6
    assert "over_0_5" in summary["missing_requested_markets"]


def test_full_audit_refuses_stale_board(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(
        alternatives, "preflight", lambda: "betsightly_db_staging"
    )
    monkeypatch.setattr(
        engine, "prepared_board", lambda days_ahead: (
            [], [], {"ready": True, "stale": True}
        )
    )
    with pytest.raises(RuntimeError, match="not fresh"):
        alternatives.audit()
