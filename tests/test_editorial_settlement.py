"""Settlement contracts for human-curated bets, isolated from official stats."""
from datetime import datetime, timezone

from leagues.editorial_settlement import grade_manual_slip

NOW = datetime(2026, 10, 13, 23, tzinfo=timezone.utc)


def leg(fid, home, away, market):
    return {
        "sportybet_event_id": fid, "match_id": "sportybet:" + fid,
        "home_team": home, "away_team": away, "market": market,
        "kickoff": "2026-10-13T18:00:00+00:00",
        "odds": 1.5, "editorial_manual": True,
    }


def final(home, away, h, a):
    return {
        f"{home.lower()}|{away.lower()}|2026-10-13": {
            "home_score": h, "away_score": a, "provider": "espn",
            "provider_event_id": "verified-fulltime", "score_90": f"{h}-{a}",
            "match_status": "FT",
        },
    }


def slip(*games):
    return {
        "date": "2026-10-13", "tier": "2_odds",
        "editorial_manual": True, "settlement_track": "editorial_separate",
        "booking": {"share_code": "REALBOOK", "status": "active"},
        "games": list(games), "total_odds": 2.25,
    }


def test_manual_verified_win_settles_without_touching_booking():
    record = slip(leg("one", "Arsenal", "Lille", "home_win"))
    result = grade_manual_slip(record, final("Arsenal", "Lille", 2, 1), now=NOW)
    assert result["result_status"] == "won"
    assert result["games"][0]["status"] == "won"
    assert result["games"][0]["settlement_evidence"]["provider"] == "espn"
    assert result["settled_at"] == NOW.isoformat()
    assert result["booking"] == record["booking"]
    assert "result_status" not in record
    assert "status" not in record["games"][0]


def test_one_losing_leg_loses_manual_accumulator_with_other_match_pending():
    record = slip(
        leg("one", "Arsenal", "Lille", "home_win"),
        leg("two", "Inter", "Juventus", "over_1_5"),
    )
    result = grade_manual_slip(record, final("Arsenal", "Lille", 0, 1), now=NOW)
    assert result["result_status"] == "lost"
    assert [g["status"] for g in result["games"]] == ["lost", "pending"]
    assert result["pending_legs"] == 1


def test_all_winning_manual_goals_legs_is_accumulator_win():
    scores = {}
    scores.update(final("Arsenal", "Lille", 2, 0))
    scores.update(final("Inter", "Juventus", 1, 1))
    record = slip(
        leg("one", "Arsenal", "Lille", "over_1_5"),
        leg("two", "Inter", "Juventus", "btts_yes"),
    )
    result = grade_manual_slip(record, scores, now=NOW)
    assert result["result_status"] == "won"
    assert result["pending_legs"] == 0
    assert result["settled_legs"] == 2


def test_missing_or_ambiguous_final_score_does_not_invent_result():
    record = slip(leg("one", "Arsenal", "Lille", "home_win"))
    result = grade_manual_slip(record, {}, now=NOW)
    assert result["result_status"] == "pending"
    assert result["games"][0]["settlement_pending_reason"] == "FINAL_SCORE_UNVERIFIED"
    ambiguous = {"arsenal|lille|2026-10-13": {"ambiguous": True}}
    result = grade_manual_slip(record, ambiguous, now=NOW)
    assert result["result_status"] == "pending"
    assert result["games"][0]["settlement_pending_reason"] == "AMBIGUOUS_FIXTURE"


def test_completed_manual_outcome_is_immutable_when_later_scores_disagree():
    record = slip(leg("one", "Arsenal", "Lille", "home_win"))
    settled = grade_manual_slip(record, final("Arsenal", "Lille", 0, 2), now=NOW)
    later = grade_manual_slip(settled, final("Arsenal", "Lille", 3, 0), now=NOW)
    assert settled["result_status"] == "lost"
    assert later == settled
    assert later["games"][0]["settlement_evidence"]["home_score"] == 0
