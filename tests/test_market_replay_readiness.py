"""Market readiness is evidence, not an activation switch."""
from __future__ import annotations
import json
from scripts.check_market_replay import audit_market_replay


def test_missing_over05_replay_is_not_mistaken_for_live_training(tmp_path):
    for file, data in {
        "replay_metadata": {"code_revision":"abc", "markets_evaluated":["over_1_5"]},
        "market_summary": {"over_1_5":{"n":300,"ece":0.01}},
        "calibration_buckets": {"over_1_5":{"90-100":{"n":300}}},
        "league_market_summary": {"over_1_5":{"a":{"n":300}}},
        "recency_market_summary": {"over_1_5":{"all":{"n":300}}},
    }.items():
        (tmp_path / (file + ".json")).write_text(json.dumps(data))
    result = audit_market_replay(tmp_path)
    assert result["status"] == "INCOMPLETE"
    assert result["markets"]["over_0_5"]["reason"] == "REPLAY_MISSING"
    assert result["markets"]["over_0_5"]["replay_ready"] is False
    assert result["model_retraining_verified"] is False
    assert result["live_calibration_verified"] is False


def test_missing_market_artifacts_fail_closed(tmp_path):
    result = audit_market_replay(tmp_path)
    assert result["status"] == "INCOMPLETE"
    assert "market_summary" in result["missing_files"]


def test_unpriced_team_markets_may_have_replay_but_not_bookmaker_benchmark(tmp_path):
    from leagues.market_registry import MARKETS
    import hashlib
    code = tmp_path / "fake_replay.py"
    code.write_text("test source")
    revision = hashlib.sha256(code.read_bytes()).hexdigest()[:16]
    cells = {key:{"n":250,"ece":0.012,"bookmaker_n":0}
             for key,spec in MARKETS.items() if spec.activation=="ACTIVE"}
    sources = {
        "replay_metadata":{"code_revision":revision,
          "markets_evaluated":list(cells),"date_range":["2001-01-01","2026-01-01"]},
        "market_summary":cells,
        "calibration_buckets":{key:{"70-75":{"n":250}} for key in cells},
        "league_market_summary":{key:{"test_league":{"n":250}} for key in cells},
        "recency_market_summary":{key:{"all":{"n":250}} for key in cells},
    }
    for key,data in sources.items():
        (tmp_path/(key+".json")).write_text(json.dumps(data))
    result = audit_market_replay(tmp_path,code_path=code)
    assert result["status"]=="REPLAY_READY"
    assert result["markets"]["over_0_5"]["replay_ready"] is True
    assert result["markets"]["over_0_5"]["bookmaker_skill_verified"] is False
    assert result["markets"]["home_over_0_5"]["reason"]=="BOOKMAKER_BENCHMARK_MISSING"
