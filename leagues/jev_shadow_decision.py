"""Constrained TypeSafe Jev 1.14 Gateway adapter: ADVISORY SHADOW ONLY.

No network without *three* deliberate safeguards: non-production runtime,
explicit shadow flag, explicit API-call flag, and a server-only Gateway key.
Jev judgment is never a sports-outcome probability, official publication
permission, bookmaker confirmation, injury verification or settlement source.

Gateway contract: POST https://ai-gateway.vercel.sh/v1/evaluate
uses model/state/keyed typed questions and returns named answers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

from leagues.jev_evidence_contract import (
    JEV_GATEWAY_ENDPOINT, JEV_MODEL_ID, shadow_readiness,
)

LOG = logging.getLogger(__name__)
MAX_STATE_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_CALLS_PER_DAY = 24
_TIMEOUT = 7
_COUNTER_LOCK = threading.Lock()
_COUNTER = {"date": None, "attempted": 0}
_CATEGORIES = frozenset({"supported", "conflicted", "insufficient"})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def runtime_status(environ=None):
    env = os.environ if environ is None else environ
    base = shadow_readiness(env)
    role = str(env.get("ENVIRONMENT", "")).strip().lower()
    active = str(env.get("BETSIGHTLY_JEV_API_CALLS_ENABLED", "")).lower() in {
        "true", "yes", "1",
    }
    # Production is ALWAYS disabled in the initial research implementation.
    if role in {"production", "prod"}:
        return {**base, "status": "production_calls_disabled",
                "network_allowed": False}
    if not active:
        return {**base, "status": "api_calls_disabled", "network_allowed": False}
    if not base["configured"]:
        return {**base, "network_allowed": False}
    return {**base, "status": "shadow_network_eligible",
            "network_allowed": True, "daily_worker_cap": MAX_CALLS_PER_DAY}


def build_request(envelope):
    if not isinstance(envelope, dict) or envelope.get("status") != "ready_for_shadow_review":
        raise ValueError("unverified evidence envelope")
    if envelope.get("publication_authority") is not False or envelope.get("shadow_only") is not True:
        raise ValueError("envelope is not shadow-only")
    state = envelope.get("state")
    if not isinstance(state, dict) or not state.get("selection") or not state.get("evidence"):
        raise ValueError("missing evidence")
    raw = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("evidence payload too large")
    return {
        "model": JEV_MODEL_ID,
        "state": state,
        "questions": {
            "evidence_state": {
                "type": "choice",
                "instructions": (
                    "Classify only whether the supplied, cited pregame evidence "
                    "supports, conflicts with, or is insufficient to assess "
                    "the listed prediction market. Do not predict a winner "
                    "and do not infer facts absent from the state."
                ),
                "criteria": {
                    "supported": "Multiple independent, relevant, dated facts support the selection.",
                    "conflicted": "Dated relevant credible evidence contradicts the selection.",
                    "insufficient": "No enough independent or reliable relevant evidence is supplied.",
                },
            },
            "requires_human_review": {
                "type": "boolean",
                "instructions": (
                    "Does the provided pregame evidence contain uncertainty, "
                    "contradictions or important unknowns meriting a human review? "
                    "This is NOT the probability of the sports prediction winning."
                ),
            },
        },
    }


def _finite_probability(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("not a numeric probability")
    value = float(value)
    if value != value or not 0 <= value <= 1:
        raise ValueError("probability out of bounds")
    return value


def parse_response(body, envelope):
    """Strictly read Gateway HTTP evaluation shape; reject unknown variants."""
    if not isinstance(body, dict):
        raise ValueError("non-object result")
    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("missing answers")
    choice = answers.get("evidence_state")
    review = answers.get("requires_human_review")
    if not isinstance(choice, dict) or not isinstance(review, dict):
        raise ValueError("missing typed answers")
    category = choice.get("choice")
    if choice.get("type", "choice") != "choice" or category not in _CATEGORIES:
        raise ValueError("unknown Jev category")
    if review.get("type", "boolean") != "boolean":
        raise ValueError("unknown boolean shape")
    probability = _finite_probability(review.get("probability"))
    confidence = choice.get("confidence")
    if confidence is not None:
        confidence = _finite_probability(confidence)
    return {
        "status": "shadow_evaluated",
        "model": JEV_MODEL_ID,
        "evidence_state": category,
        "requires_human_review_probability": probability,
        "classification_confidence": confidence,
        "state_fingerprint": envelope["state_fingerprint"],
        "shadow_only": True,
        "publication_authority": False,
        "sports_win_probability_changed": False,
        "official_selection_changed": False,
    }


def _post_gateway(payload, key):
    data = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    req = Request(
        JEV_GATEWAY_ENDPOINT, data=data,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST",
    )
    with build_opener(_NoRedirect()).open(req, timeout=_TIMEOUT) as response:
        if "json" not in (response.headers.get("Content-Type") or "").lower():
            raise ValueError("non-JSON Gateway reply")
        blob = response.read(MAX_RESPONSE_BYTES + 1)
        if len(blob) > MAX_RESPONSE_BYTES:
            raise ValueError("Gateway response too large")
        return json.loads(blob)


def evaluate_shadow(envelope, *, environ=None, transport=None,
                    now=None):
    """One bounded optional Jev evaluation; errors preserve original picks."""
    env = os.environ if environ is None else environ
    readiness = runtime_status(env)
    if not readiness["network_allowed"]:
        return {"status": readiness["status"], "shadow_only": True,
                "publication_authority": False, "network_called": False}
    try:
        payload = build_request(envelope)
    except (ValueError, TypeError, OverflowError) as exc:
        return {"status": "ineligible", "reason": type(exc).__name__,
                "shadow_only": True, "publication_authority": False,
                "network_called": False}
    utc_now = now or datetime.now(timezone.utc)
    if utc_now.tzinfo is None:
        raise ValueError("now needs timezone")
    day = utc_now.astimezone(timezone.utc).date().isoformat()
    # Process-local defence-in-depth cap. Persistent multi-worker quotas
    # are a separate acceptance gate before any shared cloud rollout.
    with _COUNTER_LOCK:
        if _COUNTER["date"] != day:
            _COUNTER.update({"date": day, "attempted": 0})
        if _COUNTER["attempted"] >= MAX_CALLS_PER_DAY:
            return {"status": "worker_call_cap_reached",
                    "shadow_only": True, "publication_authority": False,
                    "network_called": False}
        _COUNTER["attempted"] += 1
    try:
        response = (
            transport(payload, env["AI_GATEWAY_API_KEY"]) if transport is not None
            else _post_gateway(payload, env["AI_GATEWAY_API_KEY"])
        )
        return {**parse_response(response, envelope), "network_called": True}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError,
            TypeError, KeyError, json.JSONDecodeError) as exc:
        LOG.warning("Jev shadow decision unavailable: %s", type(exc).__name__)
        return {"status": "evaluation_unavailable", "reason": type(exc).__name__,
                "shadow_only": True, "publication_authority": False,
                "network_called": True}
