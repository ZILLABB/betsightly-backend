"""Disabled-by-default weekly challenger orchestration.

The public API process never imports or schedules this module. An operator may
run it in an isolated worker only after explicitly enabling the experiment.
The workflow registers evidence and challengers but cannot promote a model.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from leagues.challenger_registry import ChallengerRegistry


WORKFLOW_VERSION = "weekly-football-learning-v1"
ENV_ENABLE = "ENABLE_WEEKLY_CHALLENGER_TRAINING"
MIN_NEW_TRUSTED_MATCHES = 100


def enabled() -> bool:
    return os.getenv(ENV_ENABLE, "false").strip().lower() in {"1", "true", "yes"}


def proposed_schedule() -> dict:
    return {
        "enabled": False,
        "proposal": "weekly isolated worker, off-peak, no API-worker execution",
        "activation_requires_owner_approval": True,
    }


def dataset_fingerprint(matches: list[dict]) -> str:
    canonical = json.dumps(matches, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile_matches(matches: list[dict]) -> tuple[list[dict], dict]:
    accepted, rejected, seen = [], [], set()
    for row in matches:
        fixture_id = str(row.get("fixture_id") or "").strip()
        status = str(row.get("status") or "").upper()
        league = str(row.get("league_id") or "").strip()
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        kickoff = str(row.get("kickoff") or "").strip()
        score_ok = isinstance(row.get("home_score"), int) and isinstance(row.get("away_score"), int)
        key = fixture_id or f"{league}|{kickoff}|{home}|{away}"
        reason = None
        if status not in {"FINISHED", "SETTLED"}: reason = "NOT_FINAL"
        elif not league or not home or not away or not kickoff: reason = "IDENTITY_INCOMPLETE"
        elif home == away: reason = "DUPLICATE_TEAM_IDENTITY"
        elif not score_ok: reason = "SCORE_UNRESOLVED"
        elif key in seen: reason = "DUPLICATE_FIXTURE"
        if reason:
            rejected.append({"key": key, "reason": reason})
            continue
        seen.add(key)
        accepted.append(dict(row))
    accepted.sort(key=lambda row: (str(row.get("kickoff")), str(row.get("fixture_id"))))
    return accepted, {"accepted": len(accepted), "rejected": len(rejected),
                      "rejections": rejected}


def run_weekly(*, run_date: str, matches: list[dict], registry_path: str | Path,
               train_challenger: Callable[[list[dict], str], dict],
               evaluate_challenger: Callable[[dict], dict]) -> dict:
    if not enabled():
        raise PermissionError("WEEKLY_CHALLENGER_TRAINING_DISABLED")
    registry = ChallengerRegistry(registry_path)
    accepted, quality = reconcile_matches(matches)
    fingerprint = dataset_fingerprint(accepted)
    run_key = f"{WORKFLOW_VERSION}:{run_date}:{fingerprint}"
    prior = registry.read().get("runs", {}).get(run_key)
    if prior:
        return prior
    started = datetime.now(timezone.utc).isoformat()
    if len(accepted) < MIN_NEW_TRUSTED_MATCHES:
        record = {
            "status": "SKIPPED_INSUFFICIENT_NEW_DATA", "run_key": run_key,
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
            "workflow_version": WORKFLOW_VERSION, "data_quality": quality,
            "dataset_fingerprint": fingerprint, "production_changed": False,
        }
        return registry.record_run(run_key, record)
    try:
        challenger = train_challenger(accepted, run_key)
        evaluation = evaluate_challenger(challenger)
        record = {
            "status": "CHALLENGER_REGISTERED", "run_key": run_key,
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
            "workflow_version": WORKFLOW_VERSION, "data_quality": quality,
            "dataset_fingerprint": fingerprint, "challenger": challenger,
            "evaluation": evaluation, "production_changed": False,
            "promotion": "HUMAN_REVIEW_REQUIRED",
        }
    except Exception as exc:
        record = {
            "status": "FAILED", "run_key": run_key, "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "workflow_version": WORKFLOW_VERSION, "data_quality": quality,
            "dataset_fingerprint": fingerprint,
            "failure_reason": type(exc).__name__, "production_changed": False,
        }
    return registry.record_run(run_key, record)
