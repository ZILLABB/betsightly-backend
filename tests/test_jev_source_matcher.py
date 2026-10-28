from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest

from leagues.jev_source_matcher import match_source_fixture, matched_evidence_envelope

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=3)


def prediction(**changes):
    data = {"match_id": "espn-91", "market": "over_1_5",
            "league_slug": "ger.1", "home_team": "FC Köln",
            "away_team": "Bayern München", "kickoff": KO.isoformat(),
            "odds": 1.6, "selection_probability": .74}
    return {**data, **changes}


def source_fixture(**changes):
    data = {"source_id": "openligadb", "provider_match_id": "59123",
            "home_team": "FC Koln", "away_team": "Bayern Munchen",
            "league_shortcut": "bl1", "kickoff_utc": KO.isoformat(),
            "source_url": "https://api.openligadb.de/getmatchdata/59123"}
    return {**data, **changes}


def snapshot(fixtures=None, **changes):
    items = fixtures if fixtures is not None else [source_fixture()]
    data = {"status": "ok", "source_id": "openligadb",
            "captured_at": NOW.isoformat(), "license": "ODbL",
            "attribution": "OpenLigaDB ODbL",
            "fixtures": items, "evidence": [
                {"type": "competition_schedule",
                 "source_id": "openligadb:bl1:59123",
                 "source_url": "https://api.openligadb.de/getmatchdata/59123",
                 "claim": "Fixture reported",
                 "observed_at": NOW.isoformat()},
                {"type": "competition_schedule",
                 "source_id": "openligadb:bl1:OTHER",
                 "source_url": "https://api.openligadb.de/getmatchdata/OTHER",
                 "claim": "Different game",
                 "observed_at": NOW.isoformat()}]}
    return {**data, **changes}


def test_unique_cross_source_mapping_is_verified_with_provenance():
    result = match_source_fixture(prediction(), snapshot(), as_of=NOW)
    assert result["status"] == "matched"
    assert result["external_match_id"] == "59123"
    assert result["mapping_verified"] is True


def test_only_unique_matching_fixture_evidence_reaches_jev():
    s = snapshot()
    original = deepcopy(s)
    result = matched_evidence_envelope(prediction(), s, as_of=NOW)
    assert result["status"] == "ready_for_shadow_review"
    assert result["evidence_count"] == 1
    assert result["source_fixture_identity"]["original_fixture_id"] == "espn-91"
    assert result["state"]["evidence"][0]["source_id"] == "openligadb:bl1:59123"
    assert s == original
    assert result["publication_authority"] is False


@pytest.mark.parametrize("p,expected", [
    ({"league_slug": "ger.3"}, "no_approved_league_mapping"),
    ({"league_slug": "eng.1"}, "no_approved_league_mapping"),
    ({"away_team": "Different Side"}, "fixture_not_matched"),
    ({"home_team": "Bayern München", "away_team": "FC Köln"}, "fixture_not_matched"),
    ({"kickoff": (KO + timedelta(minutes=20)).isoformat()}, "fixture_not_matched"),
    ({"kickoff": (NOW - timedelta(minutes=1)).isoformat()}, "invalid_or_started_prediction"),
])
def test_unsupported_or_mismatched_games_quarantined(p, expected):
    result = match_source_fixture(prediction(**p), snapshot(), as_of=NOW)
    assert result["reason"] == expected


def test_ambiguous_dual_fixture_is_never_guess_mapped():
    rows = [source_fixture(provider_match_id="59123"),
            source_fixture(provider_match_id="99999")]
    result = match_source_fixture(prediction(), snapshot(rows), as_of=NOW)
    assert result["reason"] == "ambiguous_fixture"
    assert result["candidate_count"] == 2


def test_reused_external_id_is_quarantined():
    rows = [source_fixture(), source_fixture(home_team="Other",
            provider_match_id="59123")]
    result = match_source_fixture(prediction(), snapshot(rows), as_of=NOW)
    assert result["reason"] == "provider_fixture_id_reused"


@pytest.mark.parametrize("changes,reason", [
    ({"captured_at": (NOW + timedelta(minutes=1)).isoformat()}, "future_stale_or_post_kickoff_snapshot"),
    ({"captured_at": (NOW - timedelta(hours=13)).isoformat()}, "future_stale_or_post_kickoff_snapshot"),
    ({"status": "unavailable"}, "untrusted_or_unavailable_snapshot"),
    ({"license": "unknown"}, "untrusted_or_unavailable_snapshot"),
])
def test_invalid_or_stale_source_is_never_used(changes, reason):
    assert match_source_fixture(prediction(), snapshot(**changes), as_of=NOW)["reason"] == reason


def test_other_fixture_article_cannot_be_used():
    obj = snapshot(evidence=[{"source_id": "openligadb:bl1:other",
        "source_url": "https://api.openligadb.de/getmatchdata/other",
        "type": "competition_schedule", "observed_at": NOW.isoformat(),
        "claim": "unrelated"}])
    r = matched_evidence_envelope(prediction(), obj, as_of=NOW)
    assert r["reason"] == "no_matching_pregame_evidence"


def test_future_observation_is_rejected_even_when_match_id_matches():
    obj = snapshot()
    obj["evidence"][0]["observed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    r = matched_evidence_envelope(prediction(), obj, as_of=NOW)
    assert r["reason"] == "evidence_failed_timestamp_gate"


def test_raw_engine_pick_shape_supported():
    data = {"match_id": "espn-91", "market": "over_1_5", "odds": 1.6,
            "_fixture": {"league_slug": "ger.1", "commence_time": KO.isoformat(),
                         "home": {"name": "FC Köln"},
                         "away": {"name": "Bayern München"}}}
    assert match_source_fixture(data, snapshot(), as_of=NOW)["status"] == "matched"
