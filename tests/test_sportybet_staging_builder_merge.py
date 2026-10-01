"""Batch 6I staging-only SportyBet supplemental Builder merge."""
from datetime import datetime, timedelta, timezone
import time
from pathlib import Path

from leagues import engine
from leagues.sportybet_shadow_evidence import (
    staging_builder_merge_candidates,
)


def _pick(
    market="over_1_5",
    *,
    trust="TRUSTED",
    bookable=True,
    real=True,
):
    return {
        "match_id": "sportybet-shadow:fixture-1",
        "market": market,
        "market_trust_state": trust,
        "market_floor_eligible": True,
        "safe_tier_eligible": False,
        "bookable": bookable,
        "odds_are_real": real,
        "selection_probability": 0.74,
        "odds": 1.25,
        "_fixture": {
            "match_id": "sportybet-shadow:fixture-1",
            "league": "EFL League One",
            "league_slug": "eng.3",
            "competition_type": "LEAGUE",
            "competition_historical_sample": 83,
            "commence_time": (
                datetime.now(timezone.utc)
                + timedelta(days=1)
            ).isoformat(),
        },
    }


SNAPSHOT = {
    "version": "test-production-settled-v1",
    "groups": {
        "goals_over_1_5": 617,
        "goals_under_4_5": 25,
        "double_chance": 101,
        "team_goals_home": 12,
    },
}


def test_builder_merge_requires_staging_and_both_flags():
    picks = [_pick()]

    outside, outside_report = staging_builder_merge_candidates(
        picks,
        board_complete=True,
        environment="production",
        feature_flag=True,
        merge_flag=True,
        snapshot=SNAPSHOT,
    )
    assert outside == []
    assert outside_report["status"] == "not_applicable_outside_staging"

    off, off_report = staging_builder_merge_candidates(
        picks,
        board_complete=True,
        environment="staging",
        feature_flag=True,
        merge_flag=False,
        snapshot=SNAPSHOT,
    )
    assert off == []
    assert off_report["status"] == "builder_merge_flag_off"


def test_builder_merge_admits_only_full_6h_gate_winners():
    picks = [
        _pick("over_1_5"),
        _pick("home_over_0_5", trust="DEVELOPING"),
        _pick("under_4_5", bookable=False, real=False),
    ]

    eligible, report = staging_builder_merge_candidates(
        picks,
        board_complete=True,
        environment="staging",
        feature_flag=True,
        merge_flag=True,
        snapshot=SNAPSHOT,
    )

    assert report["status"] == "ready_for_builder_merge"
    assert report["eligible_candidate_count"] == 1
    assert [pick["market"] for pick in eligible] == ["over_1_5"]
    assert eligible[0]["safe_tier_eligible"] is True
    assert eligible[0]["_staging_supplemental"] is True
    assert eligible[0]["_staging_aggregate_settled_sample"] == 617
    assert eligible[0]["calibration_sample"] == 617


def test_builder_merge_does_not_mutate_shadow_pick():
    source = _pick()

    eligible, _ = staging_builder_merge_candidates(
        [source],
        board_complete=True,
        environment="staging",
        feature_flag=True,
        merge_flag=True,
        snapshot=SNAPSHOT,
    )

    assert source["safe_tier_eligible"] is False
    assert "_staging_supplemental" not in source
    assert eligible[0] is not source


def test_prepared_pipeline_does_not_expose_builder_supplemental(
    monkeypatch,
):
    now = datetime.now(timezone.utc)

    normal_fixture = {
        "match_id": "espn:normal",
        "commence_time": (
            now + timedelta(days=1)
        ).isoformat(),
    }

    normal_pick = {
        "match_id": "espn:normal",
        "_fixture": normal_fixture,
    }

    supplemental = _pick()

    entry = {
        "picks": [normal_pick],
        "fixtures": [normal_fixture],
        "builder_supplemental_picks": [supplemental],
        "ts": time.time(),
        "metadata": {
            "requested_days": 7,
            "fixture_count": 1,
            "provider": {
                "complete": True,
                "requested_league_count": 1,
                "successful_league_count": 1,
            },
            "generated_at": now.isoformat(),
            "coverage_start": now.isoformat(),
            "coverage_end": (
                now + timedelta(days=7)
            ).isoformat(),
            "decision_snapshot_id": "test",
        },
    }

    monkeypatch.setattr(
        engine,
        "_CACHE",
        {
            "entries": {7: entry},
            "healthy_entries": {7: entry},
        },
    )

    picks, fixtures = engine.prepared_pipeline(7)
    builder_only = engine.prepared_builder_supplemental_picks(7)

    assert [pick["match_id"] for pick in picks] == ["espn:normal"]
    assert [fixture["match_id"] for fixture in fixtures] == [
        "espn:normal"
    ]
    assert [pick["match_id"] for pick in builder_only] == [
        "sportybet-shadow:fixture-1"
    ]


def test_persisted_restart_keeps_supplemental_builder_only(
    monkeypatch,
):
    from leagues import prepared_board_store

    now = datetime.now(timezone.utc)

    normal_fixture = {
        "match_id": "espn:persisted-normal",
        "commence_time": (
            now + timedelta(days=1)
        ).isoformat(),
    }

    normal_pick = {
        "match_id": "espn:persisted-normal",
        "_fixture": normal_fixture,
    }

    supplemental = _pick()

    entry = {
        "picks": [normal_pick],
        "fixtures": [normal_fixture],
        "builder_supplemental_picks": [supplemental],
        "ts": time.time(),
        "metadata": {
            "requested_days": 7,
            "fixture_count": 1,
            "provider": {
                "complete": False,
                "requested_league_count": 116,
                "successful_league_count": 99,
            },
            "generated_at": now.isoformat(),
            "coverage_start": now.isoformat(),
            "coverage_end": (
                now + timedelta(days=7)
            ).isoformat(),
            "decision_snapshot_id": "persisted-isolation-test",
        },
    }

    monkeypatch.setattr(
        engine,
        "_CACHE",
        {
            "entries": {},
            "healthy_entries": {},
        },
    )
    monkeypatch.setattr(
        engine,
        "_PERSISTENCE_HYDRATED",
        False,
    )
    monkeypatch.setattr(
        prepared_board_store,
        "enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        prepared_board_store,
        "load_entries",
        lambda: [{
            "horizon_days": 7,
            "slot": "latest",
            "entry": entry,
        }],
    )

    picks, fixtures, status = engine.prepared_board(7)
    builder_only = engine.prepared_builder_supplemental_picks(7)

    assert [pick["match_id"] for pick in picks] == [
        "espn:persisted-normal"
    ]
    assert [fixture["match_id"] for fixture in fixtures] == [
        "espn:persisted-normal"
    ]
    assert [pick["match_id"] for pick in builder_only] == [
        "sportybet-shadow:fixture-1"
    ]
    assert status["board_source"] == "persistent_cache"


def test_supplemental_reader_is_not_used_by_public_modules():
    """Only engine + slip_builder may touch the Builder supplemental reader."""
    leagues_dir = Path(__file__).resolve().parents[1] / "leagues"

    allowed = {
        "engine.py",
        "slip_builder.py",
    }

    offenders = []

    for path in leagues_dir.glob("*.py"):
        if path.name in allowed:
            continue

        source = path.read_text(encoding="utf-8")

        if "prepared_builder_supplemental_picks" in source:
            offenders.append(path.name)

    assert offenders == []

