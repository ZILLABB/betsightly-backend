"""Fail-closed verification of replay evidence before market promotion.

The registry marks market *capability*, not trustworthy profitability. A live
market without a replay cell must be reported as unsupported and cannot be
silently counted as trained. This script is read-only and never publishes picks.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "replay"
REQUIRED = (
    "market_summary", "calibration_buckets",
    "league_market_summary", "recency_market_summary",
    "replay_metadata",
)
TARGETS = (
    "over_0_5", "over_1_5", "over_2_5",
    "home_over_0_5", "away_over_0_5",
    "home_over_1_5", "away_over_1_5",
    "btts_yes", "btts_no",
)


def audit_market_replay(directory: Path = DATA, code_path: Path | None = None) -> dict:
    from leagues.market_registry import MARKETS

    code_path = code_path or ROOT / "leagues" / "historical_replay.py"
    missing_files = [name for name in REQUIRED
                     if not (directory / f"{name}.json").is_file()]
    if missing_files:
        return {"status": "INCOMPLETE", "missing_files": missing_files,
                "markets": {}, "generated_at": None}

    content = {
        name: json.loads((directory / f"{name}.json").read_text())
        for name in REQUIRED
    }
    metadata = content["replay_metadata"]
    summary = content["market_summary"]
    buckets = content["calibration_buckets"]
    leagues = content["league_market_summary"]
    recency = content["recency_market_summary"]
    code_revision = hashlib.sha256(code_path.read_bytes()).hexdigest()[:16]
    stale_revision = metadata.get("code_revision") != code_revision
    targets = {}
    for key in TARGETS:
        spec = MARKETS[key]
        cell = summary.get(key) or {}
        n = int(cell.get("n") or 0)
        # A market with numerous historical matches but no exact bookmaker
        # two-way price remains unbenchmarked; do not call it trained/verified.
        bookmaker_n = int(cell.get("bookmaker_n") or 0)
        enough_replay = n >= 200 and bool((buckets.get(key) or {}))
        calibrated = cell.get("ece") is not None
        matching_margins = bool(leagues.get(key)) and bool(recency.get(key))
        evidence_complete = (enough_replay and calibrated and matching_margins
                             and key in metadata.get("markets_evaluated", []))
        targets[key] = {
            "activation": spec.activation,
            "public_policy": spec.public_policy,
            "replay_samples": n,
            "historical_ece": cell.get("ece"),
            "bookmaker_benchmark_samples": bookmaker_n,
            "bookmaker_skill_verified": bookmaker_n > 0 and
                cell.get("skill_vs_bookmaker") is not None,
            "evidence_complete": evidence_complete,
            "replay_ready": evidence_complete and not stale_revision,
            "reason": (
                "REPLAY_MISSING" if not evidence_complete
                else "REPLAY_REVISION_STALE" if stale_revision
                else "BOOKMAKER_BENCHMARK_MISSING" if not bookmaker_n
                else "HISTORICAL_EVIDENCE_AVAILABLE"
            ),
        }
    missing_active = [
        key for key, row in targets.items()
        if MARKETS[key].activation == "ACTIVE" and not row["replay_ready"]
    ]
    return {
        "status": "INCOMPLETE" if missing_active else "REPLAY_READY",
        "generated_at": metadata.get("generated_at"),
        "data_through": (metadata.get("date_range") or [None, None])[-1],
        "code_revision_matches": not stale_revision,
        "missing_active_evidence": missing_active,
        "markets": targets,
        # Replay success does NOT prove model retraining. Legacy production
        # model_training_runs is distinct from the current Poisson pipeline.
        "model_retraining_verified": False,
        "live_calibration_verified": False,
    }


if __name__ == "__main__":
    result = audit_market_replay()
    print(json.dumps(result, indent=2))
    if result["status"] != "REPLAY_READY":
        raise SystemExit(1)
