"""Stage 2D operational readiness and real-cycle ledger guards.

Only synthetic test fixtures are used. Nothing is published or sent to a
bookmaker or production service.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from basketball.research_dashboard import render_dashboard
from basketball.research_data import write_games
from basketball.research_operations import build_operations, operations_from_home
from basketball.research_readiness import build_readiness
from basketball.research_store import open_ledger, list_forecasts, performance_report

UTC = timezone.utc
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def historical_games(count=5, *, retrieved=None, now=NOW):
    games = []
    for i in range(count):
        day = (now-timedelta(days=count+1-i)).date().isoformat()
        games.append({
            "game_id": str(110+i), "date": day, "season": 2027,
            "status": "final", "home_id": "1", "away_id": "2",
            "home_name": "Home", "away_name": "Away",
            "home_score": 109, "away_score": 100,
            "start_utc": day+"T20:00:00+00:00", "postseason": False,
            "source": SOURCE, "retrieved_at": retrieved or now.isoformat(),
        })
    return games


def scheduled(ident="555", *, now=NOW, home="1", away="2",
              kickoff=None, retrieved=None):
    kickoff = kickoff or now+timedelta(hours=6)
    return {
        "game_id": ident, "date": kickoff.date().isoformat(),
        "season": 2027, "status": "scheduled",
        "home_id": home, "away_id": away,
        "home_name": "Home", "away_name": "Away",
        "home_score": None, "away_score": None,
        "start_utc": kickoff.isoformat(), "postseason": False,
        "source": SOURCE, "retrieved_at": retrieved or now.isoformat(),
    }


def _operation(games, rows=None, *, now=NOW, cycle=None, cutoff=None,
               prospective=None):
    return build_operations(
        games, rows or [], now=now,
        model_exists=True, model_cutoff=cutoff or
        (now-timedelta(days=1)).date().isoformat(),
        last_cycle=cycle or now-timedelta(minutes=5),
        prospective=prospective,
    )


def test_current_season_gate_blocks_before_five_real_finals():
    games = historical_games(4)+[scheduled()]
    report = _operation(games)
    assert report["operational_state"] == "warming_up"
    assert report["eligible_in_daily_cycle_window"] == 0
    assert report["teams_feature_ready_next_7_days"] == 0
    assert report["total_recorded_paper_forecasts"] == 0


def test_crossing_five_games_enables_first_forecast_window():
    games = historical_games(5)+[scheduled()]
    report = _operation(games, cycle=NOW-timedelta(hours=1))
    assert report["operational_state"] == "eligible_for_first_forecast"
    assert report["eligible_in_daily_cycle_window"] == 1
    assert report["eligible_not_yet_recorded"][0]["game_id"] == "555"
    assert report["warnings"] == []
    assert report["bookmaker_odds_verified"] is False


def test_completed_cycle_after_fresh_snapshot_flags_unsaved_eligible_pick():
    # Source refresh at T-10 minutes, then the cycle ran at T-3.
    retrieved = (NOW-timedelta(minutes=10)).isoformat()
    games = historical_games(5, retrieved=retrieved)+[
        scheduled(retrieved=retrieved)
    ]
    report = _operation(games, cycle=NOW-timedelta(minutes=3))
    assert "eligible_not_saved_after_cycle" in report["warnings"]
    assert report["operational_state"] == "attention_required"
    assert report["daily_cycle"]["handled_current_snapshot"] is True


def test_newer_snapshot_does_not_accuse_earlier_cycle():
    fetched = (NOW-timedelta(minutes=1)).isoformat()
    games = historical_games(5, retrieved=fetched)+[
        scheduled(retrieved=fetched)
    ]
    report = _operation(games, cycle=NOW-timedelta(minutes=3))
    assert "eligible_not_saved_after_cycle" not in report["warnings"]
    assert report["operational_state"] == "eligible_for_first_forecast"


def test_pending_and_overdue_settlement_are_distinct_states():
    games = historical_games(5)+[scheduled()]
    paper = {"game_id": "555", "start_utc": (NOW+timedelta(hours=6)).isoformat(),
             "recorded_at": None}
    first = _operation(games, [paper])
    assert first["operational_state"] == "forecast_pending_settlement"
    assert first["pending_paper_forecasts"] == 1
    assert first["overdue_pending"] == []
    kickoff = NOW-timedelta(hours=5)
    overdue_paper = {**paper, "start_utc": kickoff.isoformat()}
    later = _operation(games, [overdue_paper])
    assert later["operational_state"] == "attention_required"
    assert "overdue_pending_forecasts" in later["warnings"]
    assert later["overdue_pending"][0]["hours_since_tipoff"] == 5
    settled = {**overdue_paper, "recorded_at": NOW.isoformat()}
    done = _operation(games, [settled])
    assert done["operational_state"] == "first_settlement_verified"
    assert done["verified_paper_settlements"] == 1


def test_stale_data_and_failed_prospective_integrity_surface_warning():
    stale = (NOW-timedelta(days=3)).isoformat()
    games = historical_games(5, retrieved=stale)+[
        scheduled(retrieved=stale)
    ]
    report = _operation(
        games, prospective={"status": "integrity_failed"}
    )
    assert report["operational_state"] == "attention_required"
    assert set(report["warnings"]) >= {
        "source_not_fresh", "ledger_integrity_failed",
    }
    assert report["eligible_in_daily_cycle_window"] == 0


def test_operations_home_is_read_only_and_avoids_unpickle(tmp_path):
    games = historical_games(5)+[scheduled()]
    write_games(games, tmp_path/"nba_games.jsonl")
    (tmp_path/"nba_moneyline.joblib").write_bytes(b"not actually a model")
    (tmp_path/"training_metrics.json").write_text(json.dumps(
        {"prospective_refit": {"through": "2026-10-23"}}))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = operations_from_home(tmp_path, now=NOW)
    assert report["operational_state"] == "attention_required"
    assert "daily_cycle_not_seen" in report["warnings"]
    assert report["eligible_in_daily_cycle_window"] == 1
    assert report["no_writes"] is True
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert not (tmp_path/"nba_paper.sqlite").exists()


def test_dashboard_shows_lifecycle_without_unescaped_provider_names():
    games = historical_games(5)+[
        {**scheduled(), "home_name": "<img src=x onerror=alert(1)>"}
    ]
    ops = _operation(games, cycle=NOW-timedelta(hours=1))
    html = render_dashboard(
        {"forecast_count": 0, "settled": 0, "pending": 0},
        [], [], operations=ops,
    )
    assert "First-forecast operations" in html
    assert "READY IN DAILY WINDOW" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "Eligible, not yet recorded" in html


def test_cycle_enforces_readiness_gate_before_model_predictions_are_saved(
    tmp_path, monkeypatch,
):
    # No training, bookmaker, network, or simulated prices; mock *only* the
    # pre-existing model output to test the private write guard.
    from basketball import research_cycle as cycle
    from basketball import research_market_models
    instant = datetime.now(UTC)
    games = historical_games(5, now=instant)
    games.append(scheduled("555", now=instant))
    games.append(scheduled("556", now=instant, home="1", away="3"))
    write_games(games, tmp_path/"nba_games.jsonl")
    (tmp_path/"nba_moneyline.joblib").write_bytes(b"trusted-local-model-placeholder")
    (tmp_path/"nba_scores.joblib").write_bytes(b"trusted-score-model-placeholder")
    (tmp_path/"training_metrics.json").write_text(json.dumps({
        "prospective_refit": {
            "through": (instant-timedelta(days=1)).date().isoformat()
        }
    }))
    def model_output(games, model, day, as_of):
        if day != instant.date().isoformat():
            return []
        output = []
        for ident in ("555", "556"):
            game = next(g for g in games if g["game_id"] == ident)
            output.append({
                "game_id": ident, "date": day,
                "home_team_id": game["home_id"],
                "away_team_id": game["away_id"],
                "home_team": game["home_name"],
                "away_team": game["away_name"],
                "start_utc": game["start_utc"],
                "generated_at": datetime.now(UTC).isoformat(),
                "home_win_probability": .62,
                "away_win_probability": .38,
                "model_version": "offline-v1",
                "feature_schema": "nba-pregame-v1",
                "research_only": True, "not_for_betting": True,
                "bookmaker_odds_verified": False, "booking_code": None,
            })
        return output
    monkeypatch.setattr(cycle, "paper_forecasts", model_output)
    monkeypatch.setattr(
        research_market_models, "private_score_estimates",
        lambda games, model, day, as_of: [],
    )
    result = cycle.run_cycle(home=tmp_path, offline=True, now=instant)
    assert result["eligible_forecasts"] == 1
    assert result["new_forecasts"] == 1
    assert result["readiness"]["readiness_guard_rejected"] == 1
    with open_ledger(tmp_path/"nba_paper.sqlite") as db:
        ids = [r["game_id"] for r in list_forecasts(db)]
    assert ids == ["555"]


def test_daily_cycle_wont_create_new_picks_from_stale_fixture_snapshot(
    tmp_path, monkeypatch,
):
    from basketball import research_cycle as cycle
    from basketball import research_market_models
    now = datetime.now(UTC)
    stamp = (now-timedelta(days=5)).isoformat()
    games = historical_games(5, now=now, retrieved=stamp)
    games.append(scheduled("555", now=now, retrieved=stamp))
    write_games(games, tmp_path/"nba_games.jsonl")
    (tmp_path/"nba_moneyline.joblib").write_bytes(b"local-model-placeholder")
    (tmp_path/"nba_scores.joblib").write_bytes(b"local-score-placeholder")
    (tmp_path/"training_metrics.json").write_text(json.dumps({
        "prospective_refit": {
            "through": (now-timedelta(days=1)).date().isoformat()
        }
    }))
    def forecasts(games, model, day, as_of):
        if day == now.date().isoformat():
            fixture = games[-1]
            return [{
                "game_id": "555", "date": day, "generated_at": now.isoformat(),
                "start_utc": fixture["start_utc"]
            }]
        return []
    monkeypatch.setattr(cycle, "paper_forecasts", forecasts)
    monkeypatch.setattr(
        research_market_models, "private_score_estimates",
        lambda games, model, day, as_of: [],
    )
    report = cycle.run_cycle(home=tmp_path, offline=True, now=now)
    assert report["new_forecasts"] == 0
    assert report["readiness"]["snapshot_health"] == "stale"
    assert report["readiness"]["readiness_guard_rejected"] == 1
    with open_ledger(tmp_path/"nba_paper.sqlite") as db:
        assert performance_report(db)["forecast_count"] == 0


def test_cycle_uses_utc_tipoff_not_american_provider_date(tmp_path, monkeypatch):
    """A future NBA kickoff may carry yesterday's Eastern provider date."""
    from basketball import research_cycle as cycle
    from basketball import research_market_models
    now=datetime.now(UTC)
    provider_day=(now-timedelta(days=1)).date().isoformat()
    tipoff=now+timedelta(hours=2)
    past=historical_games(5,now=now)
    upcoming={**scheduled("overnight",now=now,kickoff=tipoff),
              "date":provider_day}
    write_games(past+[upcoming],tmp_path/"nba_games.jsonl")
    (tmp_path/"nba_moneyline.joblib").write_bytes(b"local-model-placeholder")
    (tmp_path/"nba_scores.joblib").write_bytes(b"local-score-placeholder")
    (tmp_path/"training_metrics.json").write_text(json.dumps({
        "prospective_refit":{
            "through":(now-timedelta(days=3)).date().isoformat()
        }
    }))
    seen=[]
    def forecast(games,model,day,as_of):
        seen.append(day)
        if day!=provider_day:
            return []
        return [{
            "game_id":"overnight","date":provider_day,
            "home_team_id":"1","away_team_id":"2",
            "home_team":"Home","away_team":"Away",
            "start_utc":tipoff.isoformat(),
            "generated_at":datetime.now(UTC).isoformat(),
            "home_win_probability":0.61,"away_win_probability":0.39,
            "model_version":"nba-moneyline-offline-v1",
            "feature_schema":"nba-pregame-v1",
            "research_only":True,"not_for_betting":True,
            "bookmaker_odds_verified":False,"booking_code":None,
        }]
    monkeypatch.setattr(cycle,"paper_forecasts",forecast)
    monkeypatch.setattr(research_market_models,
                        "private_score_estimates",lambda *a,**kw:[])
    result=cycle.run_cycle(home=tmp_path,offline=True,now=now)
    assert seen == [provider_day]
    assert result["new_forecasts"]==1
    assert result["readiness"]["forecast_provider_dates"]==[provider_day]
    with open_ledger(tmp_path/"nba_paper.sqlite") as db:
        assert [row["game_id"] for row in list_forecasts(db)]==["overnight"]
    ops=operations_from_home(tmp_path,now=now)
    assert ops["eligible_in_daily_cycle_window"]==1
    assert ops["already_recorded_in_daily_window"]==1
    assert ops["daily_cycle"]["expected_window"]=="Next 48 hours by verified UTC tipoff"
