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


def test_oct19_official_id_scoped_braga_settles_manual_5x_loss():
    """Public official league final settles only the matching editorial leg."""
    from leagues.results_checker import _index_free_finals
    from services.verified_incident_finals import incident_finals
    now = datetime(2026, 10, 20, 7, tzinfo=timezone.utc)
    losing = leg("sr:match:75243922", "Braga", "Gil Vicente Barcelos", "home_or_draw")
    losing["kickoff"] = "2026-10-19T19:15:00+00:00"
    other = leg("sr:match:other", "Kuwait SC", "Al Salibikhaet", "home_win")
    other["kickoff"] = "2026-10-19T14:40:00+00:00"
    record = {**slip(losing, other), "date": "2026-10-19", "tier": "5_odds"}
    reviewed = incident_finals([losing, other])
    assert len(reviewed) == 1
    assert reviewed[0]["provider_event_id"] == "sr:match:75243922"
    graded = grade_manual_slip(record, _index_free_finals(reviewed), now=now)
    assert graded["result_status"] == "lost"
    assert [game["status"] for game in graded["games"]] == ["lost", "pending"]
    assert graded["games"][0]["settlement_evidence"]["score_90"] == {"home": 1, "away": 2}
    assert graded["games"][0]["settlement_evidence"]["evidence_url"].startswith(
        "https://www.ligaportugal.pt/"
    )
    assert graded["booking"] == record["booking"]


def test_oct19_official_id_scoped_jong_psv_settles_ten_goal_ticket_loss():
    """Never mark goals won at 0-1; pending siblings are left pending."""
    from leagues.results_checker import _index_free_finals
    from services.verified_incident_finals import incident_finals
    now = datetime(2026, 10, 20, 7, tzinfo=timezone.utc)
    losing = leg("sr:match:72044748", "Jong PSV Eindhoven", "FC Dordrecht", "over_1_5")
    losing["kickoff"] = "2026-10-19T18:00:00+00:00"
    record = {**slip(losing), "date": "2026-10-19", "tier": "over_1_5"}
    finals = _index_free_finals(incident_finals([losing]))
    result = grade_manual_slip(record, finals, now=now)
    assert result["result_status"] == "lost"
    assert result["games"][0]["status"] == "lost"
    assert result["games"][0]["settlement_evidence"]["home_score"] == 0
    assert result["games"][0]["settlement_evidence"]["away_score"] == 1
    # Event-ID/date/team mismatches must never backfill the wrong fixture.
    wrong_id = {**losing, "sportybet_event_id": "sr:match:different"}
    wrong_day = {**losing, "kickoff": "2026-10-18T18:00:00+00:00"}
    wrong_club = {**losing, "away_team": "Roda JC Kerkrade"}
    assert incident_finals([wrong_id, wrong_day, wrong_club]) == []


def test_historical_pending_legs_are_not_dropped_from_settlement_queue():
    from leagues.editorial_settlement import _pending_manual_query
    postgres = _pending_manual_query("postgresql")
    assert "publish_date >= :earliest OR EXISTS" in postgres
    assert "COALESCE(g->>'status','pending')='pending'" in postgres
    assert "ORDER BY publish_date,tier" in postgres

    # SQLite local/test paths must remain executable.
    from sqlalchemy import create_engine, text
    db = create_engine("sqlite:///:memory:")
    with db.begin() as conn:
        conn.execute(text(
            "CREATE TABLE editorial_tier_slips "
            "(publish_date TEXT, tier TEXT, detail TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO editorial_tier_slips VALUES "
            "('2026-09-01','5_odds','{\"games\":[{\"status\":\"pending\"}]}')"
        ))
        rows = conn.execute(
            text(_pending_manual_query("sqlite")),
            {"earliest": "2026-10-10"},
        ).all()
    assert len(rows) == 1
    assert rows[0][0] == "2026-09-01"


def test_archived_manual_recovery_rotates_off_boundary_once_per_slot(monkeypatch):
    """A scheduler started at :07 must still process historical tickets."""
    from datetime import datetime, timedelta, timezone
    from leagues import editorial_settlement as es

    monkeypatch.setattr(es, "_ARCHIVE_SLOT_LAST", None)
    days = ["2026-10-01", "2026-10-02", "2026-10-03"]
    started = datetime(2026, 10, 28, 8, 7, tzinfo=timezone.utc)

    # The one-minute rapid lane must not consume historical backfill quota.
    assert es._claim_historical_recovery_day(
        days, started, full_recovery=False,
    ) is None
    first = es._claim_historical_recovery_day(days, started)
    assert first in days
    assert es._claim_historical_recovery_day(
        days, started + timedelta(minutes=3),
    ) is None

    # Another comprehensive cycle in the next 15-minute slot rotates.
    later = started + timedelta(minutes=9)
    expected = days[(int(later.timestamp()) // 900) % len(days)]
    assert es._claim_historical_recovery_day(days, later) == expected
    assert es._claim_historical_recovery_day(days, later) is None
    assert es._claim_historical_recovery_day([], later + timedelta(hours=1)) is None


def test_oct27_official_finals_recover_manual_2_5_10_odds_without_guessing():
    """Exact stored event ID, both teams and UTC kickoff gate every receipt."""
    from services.verified_incident_finals import incident_finals
    from leagues.results_checker import _index_free_finals

    fixtures = [
        ("sr:match:68214868", "FCI Levadia Tallinn", "Tartu JK Tammeka",
         "home_win", (2, 1), "won"),
        ("sr:match:74374528", "SV 07 Elversberg", "Darmstadt",
         "over_2_5", (0, 2), "lost"),
        ("sr:match:74374512", "Bochum", "Mainz",
         "over_2_5", (2, 0), "lost"),
    ]
    for event_id, home, away, market, scores_expected, verdict in fixtures:
        game = {
            "sportybet_event_id": event_id, "match_id": "sportybet:" + event_id,
            "home_team": home, "away_team": away,
            "market": market, "kickoff": "2026-10-27T16:00:00+00:00",
            "status": "pending",
        }
        observed = incident_finals([game])
        assert len(observed) == 1
        assert (observed[0]["home_score"], observed[0]["away_score"]) == scores_expected
        record = {"games": [game], "result_status": "pending",
                  "booking": {"share_code": "PRESERVED"}}
        graded = grade_manual_slip(
            record, _index_free_finals(observed),
            now=datetime(2026, 10, 28, 7, tzinfo=timezone.utc),
        )
        assert graded["result_status"] == verdict
        assert graded["booking"] == record["booking"]
        assert graded["games"][0]["settlement_evidence"]["provider"] == "verified-official-fixture-report"
        assert incident_finals([{**game, "away_team": "Different FC"}]) == []
        assert incident_finals([{**game, "kickoff": "2026-10-26T16:00:00Z"}]) == []


def test_oct15_oct22_official_conference_finals_recover_only_matching_receipts():
    from services.verified_incident_finals import incident_finals
    from leagues.results_checker import _index_free_finals
    records = [
        ("sr:match:74173166", "PFC CSKA Sofia", "Monaco",
         "2026-10-15T16:45:00Z", "away_or_draw", "won"),
        ("sr:match:74173200", "St. Truidense VV", "FC Iberia 1999",
         "2026-10-15T19:00:00Z", "over_1_5", "won"),
        ("sr:match:74173188", "Copenhagen", "Braga",
         "2026-10-15T19:00:00Z", "over_1_5", "won"),
        ("sr:match:74173224", "Crvena Zvezda", "Copenhagen",
         "2026-10-22T16:45:00Z", "over_2_5", "won"),
        ("sr:match:74173250", "Ajax", "Atalanta",
         "2026-10-22T19:00:00Z", "over_2_5", "lost"),
        ("sr:match:74173266", "FC Thun", "HNK Hajduk Split",
         "2026-10-22T19:00:00Z", "over_2_5", "lost"),
        ("sr:match:74173262", "FC Midtjylland", "St. Truidense VV",
         "2026-10-22T19:00:00Z", "over_1_5", "lost"),
    ]
    for eid, home, away, kickoff, market, expected in records:
        game = {"sportybet_event_id": eid, "home_team": home,
                "away_team": away, "kickoff": kickoff,
                "market": market, "status": "pending"}
        evidence = incident_finals([game])
        assert len(evidence) == 1
        assert evidence[0]["evidence_url"].startswith("https://www.uefa.com/")
        slip = {"games": [game], "booking": {"share_code": "IMMUTABLE"}}
        outcome = grade_manual_slip(
            slip, _index_free_finals(evidence),
            now=datetime(2026, 10, 28, 8, tzinfo=timezone.utc),
        )
        assert outcome["result_status"] == expected
        assert outcome["booking"] == slip["booking"]
        assert incident_finals([{**game, "sportybet_event_id": "sr:match:wrong"}]) == []
        assert incident_finals([{**game, "away_team": "Another Club"}]) == []
        assert incident_finals([{**game, "kickoff": "2026-10-23T19:00:00Z"}]) == []
