"""2026-10-16 manually published Rollover D2 must settle 3W/1L.

Event IDs, team names and exact UTC dates are independently sourced from
persisted tickets; scores are from official club or national league reports.
"""
from datetime import datetime, timezone

from services.verified_incident_finals import incident_finals
from leagues import results_checker as checker
from leagues.rollover_lifecycle import chain_state

PICKS = [
    {"match_id": "sportybet:sr:match:72587358",
     "sportybet_event_id": "sr:match:72587358",
     "home_team": "MFK Karvina", "away_team": "Dukla Prague",
     "commence_time": "2026-10-16T15:30:00+00:00",
     "market": "goals", "market_key": "over_1_5", "status": "pending"},
    {"match_id": "sportybet:sr:match:72300830",
     "sportybet_event_id": "sr:match:72300830",
     "home_team": "SFC Opava", "away_team": "FC Vysocina Jihlava",
     "commence_time": "2026-10-16T16:00:00+00:00",
     "market": "goals", "market_key": "over_1_5", "status": "pending"},
    {"match_id": "sportybet:sr:match:73068120",
     "sportybet_event_id": "sr:match:73068120",
     "home_team": "FC Cartagena", "away_team": "CE Europa",
     "commence_time": "2026-10-16T17:00:00+00:00",
     "market": "goals", "market_key": "over_1_5", "status": "pending"},
    {"match_id": "sportybet:sr:match:72043206",
     "sportybet_event_id": "sr:match:72043206",
     "home_team": "Widzew Lodz", "away_team": "Wisla Krakow",
     "commence_time": "2026-10-16T18:30:00+00:00",
     "market": "goals", "market_key": "over_1_5", "status": "pending"},
]


def test_all_four_strict_official_match_reports_are_found():
    matches = incident_finals(PICKS)
    assert len(matches) == 4
    assert [(
        m["home_score"], m["away_score"]) for m in matches
    ] == [(3, 0), (1, 3), (3, 0), (0, 0)]
    assert all(m["provider"] == "verified-official-fixture-report" for m in matches)
    assert all(m["evidence_url"].startswith("https://") for m in matches)


def test_missing_or_wrong_identity_never_reuses_another_report():
    for changed in [
        {"sportybet_event_id": None},
        {"sportybet_event_id": "sr:match:99999999"},
        {"home_team": "MFK Karvina U21"},
        {"away_team": "Dukla Prague Women"},
        {"commence_time": "2026-10-17T15:30:00+00:00"},
        {"commence_time": "2026-10-16T15:30:00"},  # no UTC offset
    ]:
        assert incident_finals([{**PICKS[0], **changed}]) == []


def test_shared_settlement_marks_loss_and_all_four_market_outcomes(monkeypatch):
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **k: {})
    scores, source = checker._collect_scores_for_picks(
        PICKS, allow_fallback=False,
    )
    assert "official-fixture-report" in source
    outcomes = []
    for p in PICKS:
        match = checker._lookup_settlement_score(
            scores, p["home_team"], p["away_team"], "2026-10-16")
        assert match is not None
        outcome, details = checker._settlement_detail(
            p, match, now=datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc),
        )
        assert details["settlement_evidence"]["evidence_url"].startswith("https://")
        outcomes.append(outcome)
    assert outcomes == ["won", "won", "won", "lost"]
    assert checker._rollover_day_status(outcomes) == "lost"
    decided = chain_state([
        {"date": "2026-10-15", "day_number": 1, "status": "won"},
        {"date": "2026-10-16", "day_number": 2, "status": "lost"},
    ], "2026-10-17")
    assert decided["new_chain"] is True
    assert decided["day_number"] == 1


def test_disagreement_with_another_official_final_stays_ambiguous(monkeypatch):
    from leagues.results_checker import _normalize_name
    p = PICKS[-1]
    key = (_normalize_name(p["home_team"]) + "|" +
           _normalize_name(p["away_team"]) + "|2026-10-16")
    monkeypatch.setattr(checker, "_collect_espn_scores_ranged",
                        lambda *a, **k: {key: {
                            "home_score": 3, "away_score": 0, "completed": True,
                            "provider": "different-final",
                        }})
    scores, _ = checker._collect_scores_for_picks([p], allow_fallback=False)
    assert scores[key].get("ambiguous")
