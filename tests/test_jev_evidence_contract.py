"""Batch-1 Jev pre-kickoff evidence contract tests: no external requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from leagues.jev_evidence_contract import evidence_envelope, shadow_readiness

NOW = datetime(2026, 10, 28, 11, 0, tzinfo=timezone.utc)


def pick(kickoff=None):
    return {
        "match_id": "espn-5", "market": "over_1_5",
        "home_team": "Alpha", "away_team": "Beta",
        "kickoff": (kickoff or NOW + timedelta(hours=2)).isoformat(),
        "selection_probability": 0.71,
        "sportybet_odds": 1.54, "market_trust_state": "TRUSTED",
        "_fixture": {"private": "not_for_jev"},
    }


def opinion(source="official", observed=None, claim="Player unavailable"):
    return {
        "type": "injury_suspension", "source_id": source,
        "source_url": "https://example.org/official", "claim": claim,
        "observed_at": (observed or NOW - timedelta(minutes=30)).isoformat(),
    }


def test_disabled_without_feature_flag_or_api_key():
    assert shadow_readiness({})["status"] == "disabled"
    assert shadow_readiness({"AI_GATEWAY_API_KEY": "secret"})["status"] == "disabled"


def test_flag_alone_does_not_enable_a_paid_call():
    report = shadow_readiness({"BETSIGHTLY_JEV_SHADOW_ENABLED": "true"})
    assert report["status"] == "missing_server_key"
    assert report["publication_authority"] is False


def test_readiness_never_exposes_the_credential():
    report = shadow_readiness({
        "BETSIGHTLY_JEV_SHADOW_ENABLED": "yes",
        "AI_GATEWAY_API_KEY": "do-not-log-this-secret",
    })
    assert report["configured"] is True
    assert "do-not-log-this-secret" not in repr(report)


def test_missing_kickoff_and_started_fixture_are_not_reviewed():
    no_kickoff = pick()
    no_kickoff["kickoff"] = "bad-date"
    assert evidence_envelope(no_kickoff, [], sport="football",
                             as_of=NOW)["status"] == "ineligible"
    started = pick(NOW - timedelta(minutes=1))
    assert evidence_envelope(started, [], sport="football",
                             as_of=NOW)["reason"] == "kickoff_already_started"


def test_only_predated_and_provenanced_evidence_is_accepted():
    rows = [opinion(), opinion(source="later", observed=NOW + timedelta(minutes=1)),
            opinion(source="started", observed=NOW + timedelta(hours=3)),
            {"type": "analyst_opinion", "claim": "Anonymous pick"}]
    report = evidence_envelope(pick(), rows, sport="football", as_of=NOW)
    assert report["status"] == "ready_for_shadow_review"
    assert report["evidence_count"] == 1
    assert report["rejected_evidence"]["future_or_post_kickoff"] == 2
    assert report["rejected_evidence"]["missing_provenance_or_type"] == 1
    assert len(report["state"]["evidence"]) == 1


def test_duplicates_same_source_are_removed_independent_conflict_preserved():
    rows = [opinion(), opinion(), opinion(source="independent", claim="Player available")]
    report = evidence_envelope(pick(), rows, sport="football", as_of=NOW)
    assert report["evidence_count"] == 2
    assert report["rejected_evidence"]["duplicate_same_source_claim"] == 1
    assert {e["source_id"] for e in report["state"]["evidence"]} == {
        "official", "independent"}


def test_stable_fingerprint_does_not_mutate_published_prediction():
    original = pick()
    snapshot = deepcopy(original)
    rows = [opinion(source="b"), opinion(source="a")]
    first = evidence_envelope(original, rows, sport="football", as_of=NOW)
    second = evidence_envelope(original, list(reversed(rows)),
                               sport="football", as_of=NOW)
    assert first["state_fingerprint"] == second["state_fingerprint"]
    assert original == snapshot
    assert "_fixture" not in first["state"]["selection"]
    assert first["publication_authority"] is False


def test_basketball_is_separate_and_has_no_automatic_publication():
    record = pick()
    record["market"] = "nba_moneyline"
    result = evidence_envelope(record, [opinion()], sport="basketball", as_of=NOW)
    assert result["state"]["sport"] == "basketball"
    assert result["publication_authority"] is False


def test_reject_invalid_time_and_unknown_sport():
    with pytest.raises(ValueError):
        evidence_envelope(pick(), [], sport="football",
                          as_of=datetime(2026, 10, 28, 11, 0))
    with pytest.raises(ValueError):
        evidence_envelope(pick(), [], sport="cricket", as_of=NOW)
