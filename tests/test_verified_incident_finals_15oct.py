"""Verify the 15 October 2026 Rollover Day 1 settlement from official finals.

Unlike an age-based void or forced admin unlock, these checks use exact
SportyBet event identity, team order and UTC kickoff date. Only verified
full-time results can advance the three-day chain.
"""
from datetime import datetime, timezone

from leagues import results_checker as checker
from leagues.rollover_lifecycle import chain_state
from services.verified_incident_finals import incident_finals


PICKS = [
    {
        "sportybet_event_id": "sr:match:74173148",
        "match_id": "sportybet:sr:match:74173148",
        "home_team": "Gent", "away_team": "AGF Aarhus",
        "commence_time": "2026-10-15T16:45:00+00:00",
        "market": "double_chance", "market_key": "home_or_draw",
        "status": "pending",
    },
    {
        "sportybet_event_id": "sr:match:74173204",
        "match_id": "sportybet:sr:match:74173204",
        "home_team": "Freiburg", "away_team": "FK Jablonec",
        "commence_time": "2026-10-15T19:00:00+00:00",
        "market": "goals", "market_key": "over_2_5",
        "status": "pending",
    },
    {
        "sportybet_event_id": "sr:match:74173182",
        "match_id": "sportybet:sr:match:74173182",
        "home_team": "Brighton", "away_team": "FK Kauno Zalgiris",
        "commence_time": "2026-10-15T19:00:00+00:00",
        "market": "goals", "market_key": "over_2_5",
        "status": "pending",
    },
]


def test_official_evidence_requires_exact_event_team_order_and_date():
    assert [r["score_90"] for r in incident_finals(PICKS)] == [
        {"home": 1, "away": 0},
        {"home": 3, "away": 2},
        {"home": 4, "away": 0},
    ]
    for wrong in (
        {"sportybet_event_id": "sr:match:wrong"},
        {"home_team": "Not Gent"},
        {"away_team": "Not Aarhus"},
        {"commence_time": "2026-10-16T16:45:00Z"},
        {"commence_time": "garbage"},
    ):
        altered = {**PICKS[0], **wrong}
        assert incident_finals([altered]) == []


def test_verified_finals_win_day_one_and_unlock_correct_day_two(monkeypatch):
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **kw: {})
    scores, source = checker._collect_scores_for_picks(PICKS)
    assert "official-fixture-report" in source
    assert len(scores) == 3

    results = []
    for pick in PICKS:
        data = checker._lookup_settlement_score(
            scores, pick["home_team"], pick["away_team"], "2026-10-15")
        assert data is not None
        outcome, details = checker._settlement_detail(pick, data)
        results.append(outcome)
        assert details["settlement_evidence"]["evidence_url"].startswith("https://")
        assert details["settlement_evidence"]["score_90"]

    assert results == ["won", "won", "won"]
    assert checker._rollover_day_status(results) == "won"
    state = chain_state(
        [{"date": "2026-10-15", "day_number": 1, "status": "won"}],
        "2026-10-16")
    assert state["can_generate"] is True
    assert state["day_number"] == 2
    assert state["new_chain"] is False


def test_disagreeing_provider_final_does_not_force_a_winner(monkeypatch):
    from leagues.results_checker import _normalize_name

    p = PICKS[0]
    key = (f"{_normalize_name(p['home_team'])}|"
           f"{_normalize_name(p['away_team'])}|2026-10-15")
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged",
                        lambda *a, **kw: {
                            key: {
                                "home_score": 0, "away_score": 0,
                                "completed": True,
                                "provider": "other-final",
                            }
                        })
    scores, _ = checker._collect_scores_for_picks([p], allow_fallback=False)
    assert scores[key] == {"ambiguous": True}
    outcome, details = checker._settlement_detail(
        p, checker._lookup_settlement_score(
            scores, p["home_team"], p["away_team"], "2026-10-15"))
    assert outcome == "pending"
    assert details["settlement_pending_reason"] == "AMBIGUOUS_FIXTURE"


def test_manual_record_grades_separately_and_preserves_booking(monkeypatch):
    from leagues.editorial_settlement import grade_manual_slip

    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **kw: {})
    scores, _ = checker._collect_scores_for_picks(PICKS)
    record = {
        "games": [dict(p) for p in PICKS],
        "result_status": "pending",
        "editorial_manual": True,
        "booking": {"share_code": "UNCHANGED"},
    }
    graded = grade_manual_slip(
        record, scores, now=datetime(2026, 10, 16, 7, tzinfo=timezone.utc))
    assert graded["result_status"] == "won"
    assert graded["settlement_track"] == "editorial_separate"
    assert [p["status"] for p in graded["games"]] == ["won"] * 3
    assert graded["booking"] == record["booking"]
    assert record["result_status"] == "pending"
