"""Replay quality gate keeps incomplete markets outside public promotion."""
from __future__ import annotations

import json
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location

import pytest

MODULE = Path(__file__).resolve().parent.parent / "scripts/replay_market_evidence.py"
spec = spec_from_file_location("market_evidence_cli", MODULE)
script = module_from_spec(spec)
spec.loader.exec_module(script)


def _cell(n, ece, bookmaker_n=0):
    return {"n": n, "ece": ece, "bookmaker_n": bookmaker_n}


def test_over05_missing_is_reported_and_gate_fails_closed():
    report = script.readiness_report({
        "over_1_5": _cell(800, .0035),
        "home_over_0_5": _cell(600, .0111),
    }, require_over05=True)
    assert report["gate_passed"] is False
    assert report["over05_replay_present"] is False
    assert "over_0_5" in report["missing_replay_markets"]
    assert report["historical_evidence_only"] is True
    assert report["production_promotion_authorized"] is False


def test_full_replay_can_pass_sample_gate_but_does_not_imply_bookmaker_edge():
    report = script.readiness_report({
        "over_0_5": _cell(1200, .007),
        "over_2_5": _cell(1250, .0018, 1200),
    }, require_over05=True)
    assert report["gate_passed"]
    assert report["market_evidence"]["over_0_5"]["ece_pp"] == .7
    assert report["market_evidence"]["over_0_5"]["benchmark_coverage"] == "MISSING"
    assert report["market_evidence"]["over_2_5"]["benchmark_coverage"] == "MEASURED"
    assert report["production_promotion_authorized"] is False


def test_older_replay_snapshot_honestly_exposes_unfilled_over05():
    replay_path = Path(__file__).resolve().parent.parent / "data/replay/market_summary.json"
    summary = json.loads(replay_path.read_text())
    report = script.readiness_report(summary)
    assert report["over05_replay_present"] == ("over_0_5" in summary and
        int((summary.get("over_0_5") or {}).get("n") or 0) >= 200)
    assert report["historical_evidence_only"] is True


def test_cli_refuses_to_overwrite_official_evidence(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(script, "ROOT", tmp_path)
    (tmp_path / "data/api-football").mkdir(parents=True)
    (tmp_path / "data/github-football").mkdir(parents=True)
    (tmp_path / "data/api-football/matches.csv").write_text("stub")
    (tmp_path / "data/github-football/Matches.csv").write_text("stub")
    monkeypatch.setattr(script, "load_and_deduplicate",
                        lambda *args: ([{"date": "test"}], {}))
    monkeypatch.setattr(script, "replay",
                        lambda rows: {"market_summary": {"over_0_5": _cell(500,.01)}, "run": {}})
    monkeypatch.setattr(script, "write_artifacts",
                        lambda *args: captured.setdefault("called", True))
    with pytest.raises(SystemExit) as exc:
        script.main(["--output", str(tmp_path / "data/replay")])
    assert exc.value.code == 2
    assert not captured


def test_output_is_isolated_and_checkable(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "ROOT", tmp_path)
    (tmp_path / "data/api-football").mkdir(parents=True)
    (tmp_path / "data/github-football").mkdir(parents=True)
    (tmp_path / "data/api-football/matches.csv").write_text("stub")
    (tmp_path / "data/github-football/Matches.csv").write_text("stub")
    monkeypatch.setattr(script, "load_and_deduplicate",
                        lambda *args: ([], {}))
    monkeypatch.setattr(script, "replay",
                        lambda rows: {"market_summary": {"over_0_5": _cell(500,.01)}, "run": {}})
    def fake_write(result, provenance, output, sources):
        output.mkdir(parents=True, exist_ok=True)
        (output / "replay_metadata.json").write_text("{}")
    monkeypatch.setattr(script, "write_artifacts", fake_write)
    target = tmp_path / "candidate"
    assert script.main(["--require-over05", "--output", str(target)]) == 0
    report = json.loads((target / "market_readiness_report.json").read_text())
    assert report["gate_passed"]
    assert not report["production_promotion_authorized"]
