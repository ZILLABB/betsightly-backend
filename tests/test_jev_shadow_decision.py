from copy import deepcopy
from datetime import datetime, timezone
import pytest

from leagues import jev_shadow_decision as jev

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
CONFIG = {
    "ENVIRONMENT": "staging",
    "BETSIGHTLY_JEV_SHADOW_ENABLED": "yes",
    "BETSIGHTLY_JEV_API_CALLS_ENABLED": "true",
    "AI_GATEWAY_API_KEY": "not-an-actual-credential",
}
PAYLOAD = {
    "status": "ready_for_shadow_review",
    "shadow_only": True,
    "publication_authority": False,
    "state_fingerprint": "f" * 64,
    "state": {
        "selection": {"fixture_id": "e-1", "market": "over_1_5"},
        "evidence": [{"type": "competition_schedule", "source_id": "openligadb:123",
                      "observed_at": NOW.isoformat(), "claim": "Fixture scheduled"}],
    },
}
REPLY = {
    "answers": {
        "evidence_state": {"type": "choice", "choice": "insufficient", "confidence": 0.97},
        "requires_human_review": {"type": "boolean", "probability": 0.91},
    },
}


def test_no_key_or_flags_never_call_external_service():
    for env in ({}, {"BETSIGHTLY_JEV_SHADOW_ENABLED": "yes"},
                {**CONFIG, "BETSIGHTLY_JEV_API_CALLS_ENABLED": "false"}):
        called = []
        report = jev.evaluate_shadow(PAYLOAD, environ=env,
            transport=lambda p, k: called.append(1), now=NOW)
        assert report["network_called"] is False
        assert called == []


def test_even_explicit_production_flags_do_not_grant_publication_or_network():
    report = jev.evaluate_shadow(PAYLOAD, environ={
        **CONFIG, "ENVIRONMENT": "production",
    }, transport=lambda p, k: pytest.fail("network forbidden"), now=NOW)
    assert report["status"] == "production_calls_disabled"
    assert report["publication_authority"] is False


def test_typed_questions_evaluate_evidence_not_sports_outcome():
    payload = jev.build_request(PAYLOAD)
    assert payload["model"] == "typesafe-ai/jev-1.14.0"
    assert payload["questions"]["evidence_state"]["type"] == "choice"
    assert payload["questions"]["requires_human_review"]["type"] == "boolean"
    assert "win_probability" not in payload["questions"]


def test_staging_shadow_request_has_strict_response_and_no_mutation():
    jev._COUNTER.update(date=None, attempted=0)
    called = []
    state = deepcopy(PAYLOAD)
    report = jev.evaluate_shadow(state, environ=CONFIG,
        transport=lambda p, k: called.append((p, k)) or REPLY, now=NOW)
    assert len(called) == 1
    assert report["status"] == "shadow_evaluated"
    assert report["evidence_state"] == "insufficient"
    assert report["requires_human_review_probability"] == .91
    assert report["classification_confidence"] == .97
    assert report["publication_authority"] is False
    assert report["sports_win_probability_changed"] is False
    assert state == PAYLOAD


@pytest.mark.parametrize("reply", [
    None,
    {},
    {"answers": {"evidence_state": {"type": "choice", "choice": "winner"},
                 "requires_human_review": {"type": "boolean", "probability": .7}}},
    {"answers": {"evidence_state": {"type": "choice", "choice": "supported"},
                 "requires_human_review": {"type": "boolean", "probability": float("nan")}}},
    {"answers": {"evidence_state": {"type": "choice", "choice": "supported"},
                 "requires_human_review": {"type": "boolean", "probability": True}}},
    {"answers": {"evidence_state": {"type": "choice", "choice": "supported"},
                 "requires_human_review": {"type": "noul", "noul": .7}}},
])
def test_unknown_or_malformed_models_never_receive_authority(reply):
    with pytest.raises(ValueError):
        jev.parse_response(reply, PAYLOAD)


def test_bad_gateway_result_fails_closed_and_redacts_key():
    jev._COUNTER.update(date=None, attempted=0)
    error = jev.evaluate_shadow(PAYLOAD, environ=CONFIG,
        transport=lambda p, key: {"answers": None}, now=NOW)
    assert error["status"] == "evaluation_unavailable"
    assert error["publication_authority"] is False
    assert CONFIG["AI_GATEWAY_API_KEY"] not in repr(error)


def test_refuses_no_evidence_and_unverified_envelopes():
    for row in ({}, {**PAYLOAD, "publication_authority": True},
                {**PAYLOAD, "state": {"selection": {"x": 1}, "evidence": []}}):
        assert jev.evaluate_shadow(row, environ=CONFIG,
            transport=lambda p, k: pytest.fail("No network"),
            now=NOW)["network_called"] is False


def test_staging_budget_cap_is_bounded_per_worker():
    jev._COUNTER.update(date=NOW.date().isoformat(),
                        attempted=jev.MAX_CALLS_PER_DAY)
    result = jev.evaluate_shadow(PAYLOAD, environ=CONFIG,
        transport=lambda p, k: pytest.fail("no more budget"), now=NOW)
    assert result["status"] == "worker_call_cap_reached"
    assert result["network_called"] is False
