"""Manual publication coverage gates and append-only score evidence tests."""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from leagues import editorial_manual as editor
from leagues import manual_settlement_evidence as evidence
from growth.api import router


def test_strict_coverage_gate_blocks_unsupported_fixture(monkeypatch):
    monkeypatch.setenv("MANUAL_SETTLEMENT_GATE_STRICT", "true")
    unknown = [{
        "sportybet_event_id": "sr:match:800", "kickoff": "2026-10-28T16:00:00Z",
        "score_competition_mapped": False, "settlement_source_candidates": [],
    }]
    blocked = editor._settlement_publication_policy(unknown)
    assert not blocked["allowed"] and blocked["mode"] == "BLOCKED"
    assert "sr:match:800" in blocked["reason"]
    bad_override = editor._settlement_publication_policy(
        unknown, manual_review_override=True, manual_review_reason="Okay")
    assert not bad_override["allowed"]
    review = editor._settlement_publication_policy(
        unknown, manual_review_override=True,
        manual_review_reason="I will verify the official FT 90-minute score manually.")
    assert review["allowed"] and review["mode"] == "EXPLICIT_MANUAL_REVIEW"
    assert review["uncovered_event_ids"] == ["sr:match:800"]
    known = [{
        **unknown[0], "score_competition_mapped": True,
        "settlement_source_candidates": ["espn"],
    }]
    assert editor._settlement_publication_policy(known)["mode"] == "AUTO_SOURCE_REGISTERED"


def test_gate_is_staged_behind_explicit_release_flag(monkeypatch):
    monkeypatch.delenv("MANUAL_SETTLEMENT_GATE_STRICT", raising=False)
    unsupported = [{"sportybet_event_id":"x", "kickoff":"2026-10-28T16:00:00Z"}]
    policy = editor._settlement_publication_policy(unsupported)
    assert policy["allowed"] and policy["mode"] == "LEGACY_WARN_ONLY"


def _ticket(share_code, event_status="pending"):
    return {
        "result_status": "pending",
        "booking": {"share_code": share_code, "final_booked_legs": [
            {"event_id": "sr:match:800"}]},
        "games": [{
            "sportybet_event_id": "sr:match:800",
            "match_id": "sportybet:sr:match:800",
            "home_team": "Arsenal", "away_team": "Lille",
            "kickoff": "2026-10-13T15:00:00Z", "league": "UEFA Champions League",
            "market": "over_1_5", "status": event_status,
        }, {
            "sportybet_event_id": "sr:match:other",
            "home_team": "Team C", "away_team": "Team D",
            "kickoff": "2026-10-13T16:00:00Z", "league": "Cup",
            "market": "over_2_5", "status": "pending",
        }],
    }


def _db(monkeypatch):
    import database
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE editorial_tier_slips (
                publish_date TEXT NOT NULL,
                tier TEXT NOT NULL,
                detail TEXT NOT NULL,
                PRIMARY KEY (publish_date, tier))
        """))
        for tier, code in (("2_odds","CODE-2"),("5_odds","CODE-5")):
            conn.execute(text("""
                INSERT INTO editorial_tier_slips (publish_date,tier,detail)
                VALUES (:d,:t,:payload)
            """), {"d":"2026-10-13", "t":tier,
                   "payload":json.dumps(_ticket(code))})
    monkeypatch.setattr(evidence, "_now",
                        lambda: datetime(2026,10,28,10,tzinfo=timezone.utc))
    return engine


def _propose():
    return evidence.propose_evidence(
        publish_date="2026-10-13", tier="2_odds",
        event_id="sr:match:800", home_score=2, away_score=1,
        evidence_url="https://www.uefa.com/uefachampionsleague/match/123",
        evidence_note="I reviewed the official finished match and checked that the score was at 90 minutes, not after extra time.",
        actor="admin")


def test_proposal_does_not_settle_or_expose_booking_and_approval_is_exact(monkeypatch):
    engine = _db(monkeypatch)
    proposed = _propose()
    assert proposed["status"] == "AWAITING_EXPLICIT_APPROVAL"
    with engine.connect() as conn:
        record = json.loads(conn.execute(text(
            "SELECT detail FROM editorial_tier_slips WHERE tier='2_odds'")).scalar())
        assert record["games"][0]["status"] == "pending"
        assert record["booking"]["share_code"] == "CODE-2"

    with pytest.raises(ValueError, match="exact SportyBet event ID"):
        evidence.approve_evidence(
            review_id=proposed["review_id"], confirmed_event_id="sr:match:wrong",
            attest_regulation_90=True, actor="admin")
    with pytest.raises(ValueError, match="attestation"):
        evidence.approve_evidence(
            review_id=proposed["review_id"], confirmed_event_id="sr:match:800",
            attest_regulation_90=False, actor="admin")

    applied = evidence.approve_evidence(
        review_id=proposed["review_id"], confirmed_event_id="sr:match:800",
        attest_regulation_90=True, actor="admin")
    assert applied["status"] == "APPROVED_AND_SETTLED"
    assert applied["legs_updated"] == 2
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT tier,detail FROM editorial_tier_slips ORDER BY tier")).all()
        for tier, raw in rows:
            result = json.loads(raw)
            assert result["booking"]["share_code"] == f"CODE-{tier.split('_')[0]}"
            assert result["games"][0]["status"] == "won"
            assert result["games"][1]["status"] == "pending"
            assert result["games"][0]["settlement_evidence"]["provider"] == "admin-reviewed-official-evidence"
            assert result["result_status"] == "pending"
        audit = conn.execute(text(
            "SELECT stage,record FROM manual_settlement_review_audit "
            "ORDER BY stage")).all()
        assert {r[0] for r in audit} == {"proposed", "approved"}
        assert json.loads(next(r[1] for r in audit if r[0] == "approved"))["changed_tickets"]
    again = evidence.approve_evidence(
        review_id=proposed["review_id"], confirmed_event_id="sr:match:800",
        attest_regulation_90=True, actor="admin")
    assert again["status"] == "ALREADY_APPROVED"


def test_bad_source_and_terminal_event_cannot_be_reviewed(monkeypatch):
    engine = _db(monkeypatch)
    with pytest.raises(ValueError, match="public official HTTPS"):
        evidence.propose_evidence(
            publish_date="2026-10-13", tier="2_odds",event_id="sr:match:800",
            home_score=1, away_score=0,
            evidence_url="http://127.0.0.1/internal",
            evidence_note="This is a detailed note for checking the correct fixture and full-time score at 90 minutes.",
            actor="admin")
    with pytest.raises(ValueError, match="45–1000"):
        evidence.propose_evidence(
            publish_date="2026-10-13",tier="2_odds",event_id="sr:match:800",
            home_score=1,away_score=0,
            evidence_url="https://official.example.com/match",
            evidence_note="Short",actor="admin")
    with engine.begin() as conn:
        t = _ticket("CODE-2", "won")
        conn.execute(text(
            "UPDATE editorial_tier_slips SET detail=:p WHERE tier='2_odds'"
        ), {"p":json.dumps(t)})
    with pytest.raises(ValueError, match="already graded"):
        _propose()


def test_evidence_routes_require_admin():
    from growth.admin_auth import require_admin
    for suffix in ("propose", "approve"):
        route = next(r for r in router.routes
                     if getattr(r,"path","") ==
                     f"/manual-tiers/settlement-review/{suffix}")
        assert require_admin in [dep.call for dep in route.dependant.dependencies]
        assert "POST" in route.methods
