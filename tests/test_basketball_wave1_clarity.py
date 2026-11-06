"""Private NBA Wave 1 operator clarity checks — synthetic, read-only."""
import json
from datetime import datetime, timezone

from basketball import research_wave1_report as module
from basketball.research_data import write_games

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def _game(ident, date, home, away, status="final"):
    return {
        "game_id": str(ident), "season": 2027, "date": date,
        "status": status, "home_id": home, "away_id": away,
        "home_name": f"Team {home}", "away_name": f"Team {away}",
        "home_score": 110 if status == "final" else None,
        "away_score": 105 if status == "final" else None,
        "start_utc": date+"T20:00:00+00:00",
        "postseason": False, "source": SOURCE,
        "retrieved_at": NOW.isoformat(),
    }


def test_nearest_to_first_forecast_uses_only_verified_earlier_results(tmp_path, monkeypatch):
    games = [_game(n, f"2026-10-{19+n:02}", "A", "B")
             for n in range(4)]
    games += [_game(20+n, f"2026-10-{19+n:02}", "C", "D")
              for n in range(3)]
    games += [_game(90, "2026-10-26", "A", "C", "scheduled"),
              _game(91, "2026-10-26", "A", "B", "scheduled")]
    write_games(games, tmp_path/"nba_games.jsonl")
    (tmp_path/"nba_moneyline.joblib").write_bytes(b"placeholder")
    (tmp_path/"training_metrics.json").write_text(json.dumps({
        "prospective_refit": {"through": "2026-10-24"}}))
    monkeypatch.setattr(module, "operations_from_home", lambda *a, **kw: {
        "warnings": [], "eligible_not_yet_recorded": [],
        "pending_paper_forecasts": 0, "verified_paper_settlements": 0,
        "total_recorded_paper_forecasts": 0})
    monkeypatch.setattr(module, "reliability_from_home", lambda *a, **kw: {
        "issues": [], "advisories": ["pregame:advanced_source_blocked"],
        "tasks": {k: {"status": "succeeded" if k != "score" else "idle"}
                  for k in ("pregame","score","full")}})
    monkeypatch.setattr(module, "stage4_report", lambda *a, **kw: {
        "current_2027_asset_health": {
            "team": {"status": "stale_coverage"},
            "player": {"status": "stale_coverage"}},
        "current_2027_lagging_assets": ["team", "player"],
        "current_2027_final_fixture_count": 7})
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = module.wave1_report(tmp_path, now=NOW)
    assert report["pregame"]["eligible_next_7_days"] == 0
    nearest = report["pregame"]["closest_to_five_verified_games"]
    assert [row["game_id"] for row in nearest] == ["91", "90"]
    assert nearest[0]["home_prior_verified"] == 4
    assert nearest[0]["away_prior_verified"] == 4
    assert nearest[0]["minimum_additional_team_finals"] == 2
    assert nearest[1]["minimum_additional_team_finals"] == 3
    assert report["pregame"]["closest_are_not_predictions"] is True
    assert report["hard_operational_issues"] == []
    assert "pregame:advanced_source_blocked" in report["nonblocking_advisories"]
    assert "advanced_2027_boxscores_stale" in report["attention"]
    assert report["automation"]["pregame_status"] == "succeeded"
    assert report["primary_next_step"] == "five_verified_earlier_games_per_team_required"
    assert report["no_writes"] is True
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_missing_advanced_assets_no_fake_near_ready(tmp_path):
    from basketball.research_wave1_report import wave1_report
    result = wave1_report(tmp_path, now=NOW)
    assert result["pregame"]["closest_to_five_verified_games"] == []
    assert result["pregame"]["eligible_next_7_days"] == 0
    assert result["release_gate"]["deployable_to_public"] is False
    assert result["no_writes"] is True
    assert list(tmp_path.iterdir()) == []
