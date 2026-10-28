"""Versioned, pre-kickoff evidence envelopes for a future Jev shadow reviewer.

Batch 1 foundation only: this module DOES NOT contact Jev, fetch external
sources, modify any candidate, approve publication or write to a database.
Real adapters must use the same source timestamp/fixture identity contract.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from typing import Any

EVIDENCE_CONTRACT_VERSION = "betsightly-evidence-v1"
JEV_MODEL_ID = "typesafe-ai/jev-1.14.0"
JEV_GATEWAY_ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
_ALLOWED_EVIDENCE_TYPES = frozenset({
    "official_team_news", "confirmed_lineup", "injury_suspension",
    "competition_schedule", "recent_results", "team_statistics",
    "independent_model", "analyst_opinion", "bookmaker_market",
})
_ALLOWED_SPORTS = frozenset({"football", "basketball"})


def _utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def shadow_readiness(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Only non-secret configuration metadata; safe to record in test logs."""
    env = os.environ if environ is None else environ
    enabled = str(env.get("BETSIGHTLY_JEV_SHADOW_ENABLED", "")).lower() in {
        "1", "true", "yes"
    }
    key_present = bool((env.get("AI_GATEWAY_API_KEY") or "").strip())
    return {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "model": JEV_MODEL_ID,
        "shadow_only": True,
        "publication_authority": False,
        "configured": bool(enabled and key_present),
        "status": ("ready_for_connection" if enabled and key_present
                   else "disabled" if not enabled else "missing_server_key"),
    }


def evidence_envelope(
    pick: dict[str, Any], observations: list[dict[str, Any]],
    *, sport: str, as_of: datetime,
) -> dict[str, Any]:
    """Snapshot independently sourced facts strictly before kickoff.

    Neither Jev nor external commentary receives authority to modify the
    caller's prediction. Every accepted observation carries provenance and
    an as-of timestamp; conflicting reports are retained separately instead
    of being merged into an invented fact.
    """
    at = _utc(as_of)
    if at is None:
        raise ValueError("as_of must be timezone-aware")
    if sport not in _ALLOWED_SPORTS:
        raise ValueError("unknown sport")
    if not isinstance(pick, dict):
        raise ValueError("prediction is required")
    fixture = str(pick.get("match_id") or "").strip()
    market = str(pick.get("market") or "").strip()
    kickoff = _utc(pick.get("kickoff") or pick.get("date")
                   or (pick.get("_fixture") or {}).get("commence_time"))
    if not fixture or not market or kickoff is None:
        return {
            "status": "ineligible",
            "reason": "missing_fixture_market_or_kickoff",
            "contract_version": EVIDENCE_CONTRACT_VERSION,
        }
    if kickoff <= at:
        return {
            "status": "ineligible", "reason": "kickoff_already_started",
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "fixture_id": fixture, "market": market,
        }

    evidence: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    seen: set[tuple[str, str, str]] = set()

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for observation in observations:
        if not isinstance(observation, dict):
            reject("invalid_observation")
            continue
        kind = str(observation.get("type") or "")
        source_id = str(observation.get("source_id") or "").strip()
        source_url = str(observation.get("source_url") or "").strip()
        claim = str(observation.get("claim") or "").strip()
        recorded = _utc(observation.get("observed_at"))
        if (kind not in _ALLOWED_EVIDENCE_TYPES or not source_id
                or not source_url.startswith("https://") or not claim
                or recorded is None):
            reject("missing_provenance_or_type")
            continue
        if recorded > at or recorded >= kickoff:
            reject("future_or_post_kickoff")
            continue
        # Do not erase conflicting evidence from independent sources; remove
        # repeated verbatim evidence from the SAME source and timestamp.
        signature = (source_id, kind, claim.casefold())
        if signature in seen:
            reject("duplicate_same_source_claim")
            continue
        seen.add(signature)
        evidence.append({
            "type": kind,
            "source_id": source_id,
            "source_url": source_url,
            "observed_at": _iso(recorded),
            "claim": claim[:2000],
        })

    evidence.sort(key=lambda row: (
        row["observed_at"], row["source_id"], row["type"], row["claim"]))

    # Only send a small, explicit subset of the model's prediction data.
    # The original pick object (and any embedded proprietary provider payload)
    # is deliberately never used as the external model's raw state.
    original = deepcopy(pick)
    selection = {
        "fixture_id": fixture,
        "market": market,
        "home_team": str(original.get("home_team") or ""),
        "away_team": str(original.get("away_team") or ""),
        "kickoff_utc": _iso(kickoff),
        "model_probability": original.get("selection_probability",
                                          original.get("confidence")),
        "bookmaker_price": original.get("sportybet_odds",
                                        original.get("odds")),
        "market_trust_state": original.get("market_trust_state"),
    }
    state = {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "sport": sport,
        "as_of": _iso(at),
        "selection": selection,
        "evidence": evidence,
    }
    digest = sha256(json.dumps(state, sort_keys=True, default=str,
                              separators=(",", ":")).encode()).hexdigest()
    return {
        "status": "ready_for_shadow_review",
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "shadow_only": True,
        "publication_authority": False,
        "state_fingerprint": digest,
        "state": state,
        "evidence_count": len(evidence),
        "rejected_evidence": rejected,
    }
