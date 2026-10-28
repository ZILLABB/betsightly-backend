"""Six-league source coverage and rights gates; all tests offline."""
from datetime import datetime, timezone
import pytest

from basketball.research_league_source_catalog import source_matrix
from basketball.research_league_source_evidence import record_probe, latest_probes
from basketball.research_multileague_release_gates import CANDIDATE_LEAGUES
from basketball.research_other_league_sources import (
    audit_candidate_payload, source_url, parse_candidate_fixture,
)
from tests.test_basketball_other_league_candidates import fixture

def test_every_league_has_bounded_source_and_explicit_license_hold():
    result=source_matrix(day="20261028",start_year=2026)
    assert result["source_candidates"] == 6
    assert set(row["league"] for row in result["leagues"]) == set(CANDIDATE_LEAGUES)
    assert result["commercially_approved_leagues"] == 0
    for row in result["leagues"]:
        assert row["source_probe_implemented"]
        assert row["reachable_now"] is None  # No invented live status.
        assert row["commercial_training_approved"] is False
        assert row["commercial_predictions_approved"] is False
        assert row["commercial_settlement_approved"] is False
        assert row["research_only"] and row["not_bookable"]
        assert row["candidate_read_url"].startswith("https://")
    assert source_url("nbl_au", "20261028") == (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nbl/"
        "scoreboard?dates=20261028&limit=100"
    )

def test_nbl_schedule_identity_count_without_fake_final():
    event=fixture()
    event["status"]={"type":{"completed":False}}
    result=audit_candidate_payload("nbl_au",{"events":[event]})
    assert result["identity_complete_fixtures"]==1
    assert result["scheduled_identity_complete"]==1
    assert result["exact_completed"]==0
    assert result["candidate_fixtures"][0]["home_id"] == "12"
    assert not result["candidate_fixtures"][0]["completed"]
    assert result["approved_for_model_training"] is False
    assert result["approved_for_non_nba_booking_settlement"] is False

def test_ambiguous_or_duplicate_fixture_rejected():
    data=fixture()
    data["competitions"][0]["competitors"][1]["team"]["id"]="12"
    assert parse_candidate_fixture("nbl_au",data) is None
    with pytest.raises(ValueError,match="DUPLICATED"):
        audit_candidate_payload("nbl_au",{"events":[fixture(),fixture()]})

class FakeSession:
    def __init__(self):
        self.statements=[]
        self.commits=0
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def execute(self,query,values):
        self.statements.append((str(query),values))
    def commit(self): self.commits+=1

def test_stored_evidence_excludes_raw_results_and_restricts_counts():
    db=FakeSession()
    result=record_probe("nbl_au","20261028",{
        "events_observed":1,"identity_complete_fixtures":1,"exact_completed":0,
        "candidate_fixtures":[{"team":"do-not-store"}],
    },session_factory=lambda:db)
    assert result["not_bookable"] and result["commercial_use_cleared"] is False
    assert db.commits==1
    sql,params=db.statements[0]
    assert "nba_research.nba_league_source_probes" in sql
    assert params["events"]==1 and params["identities"]==1
    assert params["finals"]==0 and params["complete"] is False
    assert "do-not-store" not in str(params)
    european=FakeSession()
    record_probe("euroleague","2026",{
        "season_total_claimed":380,"page_identities_checked":380,
        "page_complete":True,
    },session_factory=lambda:european)
    assert european.statements[0][1]["complete"] is True
    assert european.statements[0][1]["finals"] == 0
    for bad in ({"events_observed":1,"identity_complete_fixtures":0,
                 "exact_completed":1}, {"events_observed":-3,
                 "identity_complete_fixtures":0,"exact_completed":0}):
        with pytest.raises(ValueError,match="COUNTS_INVALID"):
            record_probe("nbl_au","20261028",bad,
                         session_factory=lambda:FakeSession())
    with pytest.raises(ValueError,match="SCOPE_INVALID"):
        record_probe("nbl_au","20261028;DROP",{},
                     session_factory=lambda:FakeSession())
    with pytest.raises(ValueError,match="INVALID"):
        record_probe("football","20261028",{},
                     session_factory=lambda:FakeSession())
