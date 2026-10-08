"""Staging tier comparison is read-only, requires fresh board, restores env."""
import os

import pytest

from scripts import compare_staging_official_market_slips as compare


def test_diff_compares_tiers_and_restores_feature_flag(monkeypatch):
    from leagues import engine, daily_feed

    monkeypatch.setenv(compare.FLAG, "user-original")
    monkeypatch.setattr(compare, "preflight", lambda: "betsightly_db_staging")
    picks = [{"match_id": "a", "_fixture": {"commence_time": "2099-01-01T21:00:00Z"}}]
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: (
        picks, [picks[0]["_fixture"]],
        {"ready": True, "stale": False, "board_snapshot_id": "sha"},
    ))
    invocations = []

    def fake_build(*, preview):
        flag = os.environ[compare.FLAG]
        invocations.append(flag)
        assert preview["picks"] is picks
        if flag == "1":
            games = [{"match_id": "a", "market": "home_or_draw"}]
        else:
            games = []
        return {"accumulators": {
            "banker": {"selected": bool(games), "games": games,
                       "total_odds": 1.5},
        }}
    monkeypatch.setattr(daily_feed, "build_daily_accumulators", fake_build)

    result = compare.compare()
    assert invocations == ["0", "1"]
    assert os.environ[compare.FLAG] == "user-original"
    assert result["mode"] == "READ_ONLY_STAGING_OFFICIAL_MARKET_ALTERNATIVES_PREVIEW"
    assert result["gain"]["banker"]["additional_legs"] == 1
    assert result["official_publication"] is False
    assert result["booking_codes_created"] is False
    assert result["quality_thresholds_changed"] is False


def test_compares_refuse_stale_board(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(compare, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: (
        [], [], {"ready": True, "stale": True}
    ))
    with pytest.raises(RuntimeError, match="stale"):
        compare.compare()


def test_duplicate_across_tiers_is_hard_failure():
    card = {"accumulators": {
        "banker": {"selected": True, "games": [
            {"match_id": "a", "market": "home_or_draw"}]},
        "5_odds": {"selected": True, "games": [
            {"match_id": "a", "market": "over_2_5"}]},
    }}
    with pytest.raises(RuntimeError, match="duplicated"):
        compare._overview(card)
