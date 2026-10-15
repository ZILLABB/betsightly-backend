"""Regressions for 14 Oct bookmaker-match settlement and new Day 1 gating.

Every score must be tied to an official final report and exact source fixture.
Never infer a winner from expired kickoffs or a fuzzy match.
"""
import json
from datetime import datetime, timezone

from services.verified_incident_finals import incident_finals
from leagues import results_checker as checker
from leagues.rollover_lifecycle import chain_state


ROLL_PICKS = [
    {
        "sportybet_event_id": "sr:match:73835212",
        "match_id": "sportybet:sr:match:73835212",
        "home_team": "Al-Taawoun FC",
        "away_team": "Al Rayyan SC",
        "commence_time": "2026-10-14T16:00:00+00:00",
        "market": "double_chance",
        "market_key": "away_or_draw",
        "status": "pending",
    },
    {
        "sportybet_event_id": "sr:match:75339776",
        "match_id": "sportybet:sr:match:75339776",
        "home_team": "Bohemians Prague 1905",
        "away_team": "FK Mlada Boleslav",
        "commence_time": "2026-10-14T16:00:00+00:00",
        "market": "double_chance",
        "market_key": "home_or_draw",
        "status": "pending",
    },
    {
        "sportybet_event_id": "sr:match:73835214",
        "match_id": "sportybet:sr:match:73835214",
        "home_team": "AL Faisaly (Jor)",
        "away_team": "Al Nahda",
        "commence_time": "2026-10-14T18:15:00+00:00",
        "market": "double_chance",
        "market_key": "home_or_draw",
        "status": "pending",
    },
]


def test_only_exact_published_ids_teams_and_dates_match_official_reports():
    import copy
    assert len(incident_finals(ROLL_PICKS)) == 3
    for replacement in (
        {"sportybet_event_id": "sr:match:wrong"},
        {"home_team": "Similar Team"},
        {"away_team": "Another Club"},
        {"commence_time": "2026-10-15T16:00:00Z"},
        {"commence_time": "not_a_date"},
    ):
        altered = copy.deepcopy(ROLL_PICKS[0])
        altered.update(replacement)
        assert incident_finals([altered]) == []
    assert incident_finals([{"home_team": ROLL_PICKS[0]["home_team"],
                             "away_team": ROLL_PICKS[0]["away_team"],
                             "commence_time": ROLL_PICKS[0]["commence_time"]}]) == []


def test_verified_reports_reconcile_yesterdays_losing_rollover(monkeypatch):
    # ESPN intentionally has no score for these source fixtures.
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **kw: {})
    scores, source = checker._collect_scores_for_picks(ROLL_PICKS)
    assert "official-fixture-report" in source
    assert len(scores) == 3
    outcomes = []
    for pick in ROLL_PICKS:
        match = checker._lookup_settlement_score(
            scores, pick["home_team"], pick["away_team"], "2026-10-14")
        assert match is not None
        outcome, details = checker._settlement_detail(pick, match)
        outcomes.append(outcome)
        assert details["settlement_evidence"]["evidence_url"].startswith("https://")
        assert details["settlement_evidence"]["score_90"]
    assert outcomes == ["lost", "won", "won"]
    assert checker._rollover_day_status(outcomes) == "lost"
    decision = chain_state([{"day_number": 1, "date": "2026-10-14",
                             "status": "lost"}], "2026-10-15")
    assert decision["can_generate"] is True
    assert decision["day_number"] == 1
    assert decision["new_chain"] is True


def test_ambiguous_disagreeing_score_stays_pending(monkeypatch):
    # Never replace a different verified result with incident evidence.
    from leagues.results_checker import _normalize_name
    original = ROLL_PICKS[0]
    key = (f"{_normalize_name(original['home_team'])}|"
           f"{_normalize_name(original['away_team'])}|2026-10-14")
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **kw: {
        key: {"home_score": 0, "away_score": 0, "completed": True,
              "provider": "other-final", "provider_event_id": "test"},
    })
    scores, _ = checker._collect_scores_for_picks([original], allow_fallback=False)
    assert scores[key] == {"ambiguous": True}
    match = checker._lookup_settlement_score(scores,
                                             original["home_team"],
                                             original["away_team"], "2026-10-14")
    outcome, details = checker._settlement_detail(original, match)
    assert outcome == "pending"
    assert details["settlement_pending_reason"] == "AMBIGUOUS_FIXTURE"


def test_manual_record_uses_same_verified_scores_not_model_roi(monkeypatch):
    from leagues.editorial_settlement import grade_manual_slip
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **kw: {})
    scores, _ = checker._collect_scores_for_picks(ROLL_PICKS)
    record = {"games": [dict(g) for g in ROLL_PICKS],
              "result_status": "pending", "editorial_manual": True,
              "source": "admin_curated", "booking": {"share_code": "REDACTED"}}
    out = grade_manual_slip(record, scores,
                            now=datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc))
    assert out["result_status"] == "lost"
    assert [g["status"] for g in out["games"]] == ["lost", "won", "won"]
    assert out["settlement_track"] == "editorial_separate"
    assert out["booking"] == record["booking"]
    assert record["result_status"] == "pending"
