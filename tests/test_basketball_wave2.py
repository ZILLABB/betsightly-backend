"""Synthetic NBA Wave 2 audit tests. No network, betting or private data."""
import copy
import hashlib
import json
from datetime import datetime, timezone

from basketball.research_wave2_report import wave2_report, _market_metrics

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _forecast():
    grid = {"status": "research_only", "no_bookmaker_odds": True,
            "thresholds_source": "fixed illustrative research grid, not sportsbook",
            "markets": {"total_points": [
                {"line": n, "above_probability": .6, "below_probability": .3,
                 "push_probability": .1} for n in (220.5, 225.5, 230.5)]}}
    row = {"game_id": "777", "season": 2027, "fixture_date": "2026-11-01",
           "start_utc": "2026-11-01T20:00:00+00:00",
           "created_at": "2026-11-01T10:00:00+00:00",
           "home_id": "1", "away_id": "2",
           "model_version": "nba-advanced-shadow-2026-v1",
           "candidate_home_win_probability": .75,
           "matched_v1_home_win_probability": .55,
           "candidate_total_points": 224, "candidate_home_margin": 4,
           "matched_v1_total_points": 226, "matched_v1_home_margin": 2,
           "market_probabilities": grid, "research_only": True,
           "not_for_betting": True, "bookmaker_odds_verified": False}
    return _hash(row)


def _hash(row):
    original = {k: v for k,v in row.items() if k != "sha256"}
    row = dict(original)
    row["sha256"] = hashlib.sha256(json.dumps(
        original, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return row


def _fixture(home=117, away=110):
    return {"game_id": "777", "season": 2027, "date": "2026-11-01",
            "status": "final", "home_id": "1", "away_id": "2",
            "home_score": home, "away_score": away, "postseason": False,
            "start_utc": "2026-11-01T20:00:00+00:00", "source": SOURCE}


def _setup(root, forecast=None, game=None, settle=True):
    forecast = forecast or _forecast()
    game = game or _fixture()
    _write(root/"advanced/shadow_2027.jsonl", json.dumps(forecast)+"\n")
    _write(root/"nba_games.jsonl", json.dumps(game)+"\n")
    if settle:
        _write(root/"advanced/shadow_settlements_2027.json", json.dumps({
            "777": {"scores": [game["home_score"], game["away_score"]],
                    "source": SOURCE, "verified_at": "2026-11-02T00:00:00+00:00"}}))


def test_cold_start_no_writes(tmp_path):
    result = wave2_report(tmp_path, now=NOW)
    assert result["status"] == "awaiting_first_forecast"
    assert result["model_promotion_approved"] is False
    assert result["betting_roi"] is None
    assert list(tmp_path.iterdir()) == []


def test_forward_same_cohort_and_push_probability(tmp_path):
    _setup(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = wave2_report(tmp_path, now=NOW)
    assert report["status"] == "descriptive_only"
    assert report["paired_moneyline"]["candidate_brier"] == .0625
    assert report["paired_moneyline"]["matched_v1_brier"] == .2025
    assert report["paired_moneyline"]["paired_brier_improvement"] == .14
    assert report["point_projection_errors"]["candidate_total_points"]["mae"] == 3
    line = next(r for r in report["market_evaluation"]["metrics"]
                if r["target"] == "total_points" and r["line"] == 220.5)
    assert line["conditional_nonpush_brier"] == round((1-.6/.9)**2, 6)
    assert not line["review_checkpoint_met"]
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_pending_never_masquerades_as_final(tmp_path):
    _setup(tmp_path, settle=False)
    result = wave2_report(tmp_path, now=NOW)
    assert result["status"] == "awaiting_verified_finals"
    assert result["pending_count"] == 1
    assert result["paired_moneyline"]["candidate_brier"] is None


def test_conflicting_final_withholds_every_metric(tmp_path):
    _setup(tmp_path)
    _write(tmp_path/"nba_games.jsonl", json.dumps(_fixture(110, 120))+"\n")
    result = wave2_report(tmp_path, now=NOW)
    assert result["status"] == "integrity_failed"
    assert result["metrics_withheld"] is True
    assert "paired_moneyline" not in result


def test_rehashed_after_tipoff_is_still_invalid(tmp_path):
    row = _forecast()
    row["created_at"] = "2026-11-01T21:00:00+00:00"
    _setup(tmp_path, forecast=_hash(row))
    assert "before_tipoff" in wave2_report(tmp_path, now=NOW)["reason"]


def test_hash_tampering_and_duplicate_fail_closed(tmp_path):
    _setup(tmp_path)
    path = tmp_path/"advanced/shadow_2027.jsonl"
    path.write_text(path.read_text()*2)
    assert wave2_report(tmp_path, now=NOW)["status"] == "integrity_failed"
    path.write_text(json.dumps({**_forecast(), "candidate_home_win_probability": .99})+"\n")
    assert wave2_report(tmp_path, now=NOW)["status"] == "integrity_failed"


def test_orphan_settlement_rejected(tmp_path):
    _setup(tmp_path)
    path = tmp_path/"advanced/shadow_settlements_2027.json"
    records = json.loads(path.read_text())
    records["ghost"] = copy.deepcopy(records["777"])
    path.write_text(json.dumps(records))
    assert "orphan" in wave2_report(tmp_path, now=NOW)["reason"]


def test_invalid_result_provenance_time_rejected(tmp_path):
    _setup(tmp_path)
    path = tmp_path/"advanced/shadow_settlements_2027.json"
    records = json.loads(path.read_text())
    records["777"]["verified_at"] = "2026-11-01T19:00:00+00:00"
    path.write_text(json.dumps(records))
    assert wave2_report(tmp_path, now=NOW)["status"] == "integrity_failed"


def test_actual_push_not_counted_as_win_or_loss(monkeypatch):
    import basketball.research_wave2_report as module
    monkeypatch.setitem(module.LINES, "total_points", (220.0,))
    row = _forecast()
    row["market_probabilities"]["markets"]["total_points"][0]["line"] = 220.0
    result = _market_metrics([(row, 111, 109)])
    item = next(r for r in result["metrics"] if r["line"] == 220.0)
    assert item["actual_pushes"] == 1
    assert item["nonpush_scored"] == 0
    assert item["conditional_nonpush_brier"] is None
