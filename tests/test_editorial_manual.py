"""Admin-only editorial tiers: strict bookmaker/event contracts and no history rewrite."""
from datetime import datetime, timedelta, timezone

import pytest

from leagues import editorial_manual as editor


def fake_board(now=None):
    at = now or datetime.now(timezone.utc)
    start = (at + timedelta(hours=3)).replace(microsecond=0)
    return {
        "__meta__": {"snapshot_id": "fixture-test"},
        "sports": [
            {"event_id": "52587", "home_team": "Arsenal",
             "away_team": "Lille", "competition": "Test Competition",
             "kickoff_ms": int(start.timestamp() * 1000),
             "prices": {"home_win": 1.3, "over_1_5": 1.25}},
            {"event_id": "52588", "home_team": "Atletico",
             "away_team": "Man United", "competition": "Test Competition",
             "kickoff_ms": int(start.timestamp() * 1000),
             "prices": {"home_win": 2.4, "over_1_5": 1.5}},
        ],
    }


def test_admin_parse_accepts_csv_and_deduplicates_fixtures():
    assert editor.parse_input(
        "event_id,market\n52587,home_win\n52588,over_1_5",
        "2_odds",
    ) == [("52587", "home_win"), ("52588", "over_1_5")]
    with pytest.raises(ValueError, match="fixture repeated"):
        editor.parse_input("52587,home_win\n52587,over_1_5", "2_odds")
    with pytest.raises(ValueError, match="only accepts"):
        editor.parse_input("52587,home_win", "over_1_5")
    with pytest.raises(ValueError, match="mapped SportyBet"):
        editor.parse_input("52587,not_a_market", "2_odds")


def test_ten_odds_cannot_be_mislabelled_or_have_more_than_twenty_legs():
    with pytest.raises(ValueError, match="10.00x"):
        editor.check_tier_target("10_odds", 9.99, 4)
    with pytest.raises(ValueError, match="Too many"):
        editor.check_tier_target("10_odds", 12, 21)


def test_exact_sportybet_event_ids_and_live_prices(monkeypatch):
    from leagues import sportybet
    now = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    board = fake_board(now)
    def availability(board, home, away, commence, league, market, event_id=None):
        assert event_id in {"52587", "52588"}
        return {
            "sportybet_available": True,
            "sportybet_odds": board["sports"][
                0 if event_id == "52587" else 1
            ]["prices"][market],
            "event_id": event_id,
        }
    monkeypatch.setattr(sportybet, "availability_for", availability)
    picks = editor._current_bookable_games(
        [("52587", "home_win"), ("52588", "over_1_5")],
        board, now=now, date="2026-10-13",
    )
    assert [g["sportybet_event_id"] for g in picks] == ["52587", "52588"]
    assert [g["odds"] for g in picks] == [1.3, 1.5]
    assert all(g["editorial_manual"] is True for g in picks)
    assert all(g["model_probability_available"] is False for g in picks)
    assert all("confidence" not in g for g in picks)


def test_manual_preview_does_not_create_booking_or_modify_locked_card(monkeypatch):
    from leagues import sportybet, booking, picks_db
    now = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    board = fake_board(now)
    monkeypatch.setattr(picks_db, "load_card", lambda d: {"banker": {"selected": False}})
    monkeypatch.setattr(booking, "bookings_for", lambda d: {})
    monkeypatch.setattr(editor, "list_published", lambda d: {})
    monkeypatch.setattr(sportybet, "availability_for",
                        lambda board, home, away, kickoff, league, market, event_id=None:
                        {"sportybet_available": True,
                         "sportybet_odds": 2.4, "event_id": event_id})
    result = editor.preview("banker", "52588,home_win", board=board, now=now)
    assert result["booking_code_created"] is False
    assert result["editorial_manual"] is True


def test_manual_preview_cannot_override_selected_automated_tier(monkeypatch):
    from leagues import picks_db
    monkeypatch.setattr(picks_db, "load_card",
                        lambda day: {"banker": {"selected": True}})
    with pytest.raises(ValueError, match="immutable official"):
        editor.preview("banker", "52587,home_win",
                       board=fake_board())


def test_manual_reuse_of_auto_rollover_is_warned_not_blocked():
    selected = [{"sportybet_event_id": "52587", "match_id": "sportybet:52587",
                 "home_team": "Arsenal", "away_team": "Lille"}]
    warnings = editor._check_exposure(
        selected, {},
        {"rollover": {"final_booked_legs": [{"sportybet_event_id": "52587"}]}},
        {}, tier="banker",
    )
    assert len(warnings) == 1
    assert warnings[0]["also_in_tiers"] == ["rollover"]
    assert "correlated" in warnings[0]["message"]



def test_editorial_overlay_does_not_overwrite_automated_tier(monkeypatch):
    monkeypatch.setattr(editor, "list_published", lambda d: {
        "banker": {"games": [], "total_odds": 1.3, "booking": {}},
    })
    base = {"banker": {"selected": True, "games": [{"match_id": "official"}]}}
    result = editor.overlay_on_card("2026-10-13", base)
    assert result["banker"] == base["banker"]


def test_editorial_overlay_applies_validated_booking_lifecycle(monkeypatch):
    from leagues import booking
    monkeypatch.setattr(editor, "list_published", lambda d: {
        "banker": {
            "games": [{"match_id": "sportybet:52587", "editorial_manual": True}],
            "total_odds": 1.3,
            "booking": {"status": "active", "share_code": "TEST01",
                        "readback_validation": "PASSED"},
        },
    })
    monkeypatch.setattr(booking, "booking_lifecycle",
                        lambda rec, games: {**rec, "share_code": None,
                                            "actionable": False, "status": "expired"})
    updated = editor.overlay_on_card("2026-10-13", {"banker": {"selected": False}})
    assert updated["banker"]["editorial_manual"] is True
    assert updated["banker"]["booking"]["status"] == "expired"
    assert updated["banker"]["booking_code"] is None
    assert updated["banker"]["hit_probability"] is None


def test_over_goals_accepts_mixed_regular_totals_only():
    assert editor.parse_input(
        "12345,over_1_5\n12346,Over 2.5\n12347,o3.5\n12348,over_4_5",
        "over_1_5",
    ) == [
        ("12345", "over_1_5"), ("12346", "over_2_5"),
        ("12347", "over_3_5"), ("12348", "over_4_5"),
    ]
    for market in ("under_4_5", "btts_no", "home_win"):
        with pytest.raises(ValueError, match="only accepts"):
            editor.parse_input(f"12345,{market}", "over_1_5")
    assert editor.parse_input("12345,over_0_5", "over_1_5") == [
        ("12345", "over_0_5")
    ]
    assert editor.parse_input("12345,o0.5", "rollover") == [
        ("12345", "over_0_5")
    ]
    assert editor.parse_input("12345,0.5", "2_odds") == [
        ("12345", "over_0_5")
    ]
    assert editor.parse_input("12345,btts_yes", "5_odds") == [
        ("12345", "btts_yes")
    ]

    # Same Over Goals tier, no replacement tier or forced market conversion.
    assert editor.parse_input(
        "12345,home_over_1_5\n12346,away_over_1_5\n12347,btts_yes",
        "over_1_5",
    ) == [
        ("12345", "home_over_1_5"),
        ("12346", "away_over_1_5"),
        ("12347", "btts_yes"),
    ]
    assert editor.parse_input("12345,home_over_0_5", "over_1_5") == [
        ("12345", "home_over_0_5")
    ]
    assert editor.parse_input("12345,away_over_1_5", "rollover") == [
        ("12345", "away_over_1_5")
    ]


def test_explicit_override_only_for_over_goals_and_never_for_other_tiers():
    card = {"over_1_5": {"selected": True},
            "banker": {"selected": True}}
    assert editor._over_display_conflict(card, "over_1_5", False)
    assert not editor._over_display_conflict(card, "over_1_5", True)
    with pytest.raises(ValueError, match="Only Over Goals"):
        editor._over_display_conflict(card, "banker", True)
    assert editor._over_display_conflict(card, "banker", False)


def test_original_over_goals_match_can_be_reused_in_own_replacement():
    same = {"sportybet_event_id": "52587", "match_id": "sportybet:52587",
            "home_team": "Arsenal", "away_team": "Lille"}
    card = {"over_1_5": {"selected": True, "games": [same]}}
    assert editor._check_exposure(
        [same], card, {}, {}, tier="over_1_5",
    ) == []  # original model ticket stays independently archived



def test_override_replaces_display_only_and_keeps_original_archive(monkeypatch):
    from leagues import booking
    original = {
        "selected": True,
        "games": [{"match_id": "official:locked",
                   "sportybet_event_id": "original-event"}],
        "presentation": "singles",
        "booking": {"share_code": "ORIGINALCODE"},
    }
    manually_booked = {
        "games": [{"match_id": "sportybet:52588", "market": "over_2_5",
                   "sportybet_event_id": "52588"}],
        "total_odds": 1.8,
        "booking": {"share_code": "MANUALCODE", "status": "active",
                    "readback_validation": "PASSED"},
        "replaces_official_display": True,
    }
    monkeypatch.setattr(editor, "list_published",
                        lambda day: {"over_1_5": manually_booked})
    monkeypatch.setattr(booking, "booking_lifecycle",
                        lambda code, games: {**code, "actionable": True})
    card = {"over_1_5": original}
    displayed = editor.overlay_on_card("2026-10-14", card)
    assert displayed["over_1_5"]["editorial_manual"] is True
    assert displayed["over_1_5"]["presentation"] == "accumulator"
    assert displayed["over_1_5"]["booking_code"] == "MANUALCODE"
    assert displayed["over_1_5"]["replaces_official_display"] is True
    assert displayed["over_1_5"]["replaced_official_selection_count"] == 1
    assert displayed["over_1_5"]["hit_probability"] is None
    assert card["over_1_5"] == original
    assert card["over_1_5"]["booking"]["share_code"] == "ORIGINALCODE"


def test_manual_rollover_odds_and_input_contract():
    assert editor.parse_input("52587,home_win\n52588,over_1_5", "rollover") == [
        ("52587", "home_win"), ("52588", "over_1_5"),
    ]
    editor.check_tier_target("rollover", 2.0, 2)
    editor.check_tier_target("rollover", 4.0, 2)
    with pytest.raises(ValueError, match="2.00x"):
        editor.check_tier_target("rollover", 1.99, 2)
    with pytest.raises(ValueError, match="2.00x–4.00x"):
        editor.check_tier_target("rollover", 4.01, 2)
    with pytest.raises(ValueError, match="Too many"):
        editor.check_tier_target("rollover", 3.0, 13)


def test_manual_rollover_requires_a_free_stage_after_prior_win():
    empty = {"rollover": {"selected": False}}
    ready = editor.rollover_eligibility(
        "2026-10-14", card=empty,
        chain={"start_date": "2026-10-14", "days": []},
    )
    assert ready["allowed"] is True
    assert ready["day_number"] == 1
    pending = editor.rollover_eligibility(
        "2026-10-14", card=empty,
        chain={"start_date": "2026-10-13", "days": [
            {"day_number": 1, "date": "2026-10-13", "status": "pending"},
        ]},
    )
    assert pending["allowed"] is False
    assert "awaiting_settlement" in pending["reason"]
    next_stage = editor.rollover_eligibility(
        "2026-10-14", card=empty,
        chain={"start_date": "2026-10-13", "days": [
            {"day_number": 1, "date": "2026-10-13", "status": "won"},
        ]},
    )
    assert next_stage["allowed"] is True
    assert next_stage["day_number"] == 2
    assert next_stage["chain_start_date"] == "2026-10-13"
    existing = editor.rollover_eligibility(
        "2026-10-14", card={"rollover": {"selected": True}},
        chain={"start_date": "2026-10-14", "days": []},
    )
    assert existing["allowed"] is False
    assert "already published" in existing["reason"]


def test_rollover_manual_picks_have_exact_settlement_market_but_no_model_confidence():
    game = {"match_id": "sportybet:52588", "sportybet_event_id": "52588",
            "home_team": "Atletico", "away_team": "Man United",
            "league": "Football", "kickoff": "2026-10-14T16:00:00+00:00",
            "prediction": "Over 1.5", "prediction_type": "goals",
            "market": "over_1_5", "odds": 1.5}
    item = editor._rollover_day_picks([game])[0]
    assert item["market_key"] == "over_1_5"
    assert item["source"] == "admin_curated"
    assert item["editorial_manual"] is True
    assert item["confidence"] is None
    from leagues.results_checker import _evaluate_pick
    assert _evaluate_pick(item, 1, 1) == "won"
    assert _evaluate_pick(item, 0, 1) == "lost"


def test_rollover_overlay_requires_proven_manual_chain(monkeypatch):
    from leagues import booking
    record = {
        "games": [{"match_id": "sportybet:52588", "sportybet_event_id": "52588"}],
        "total_odds": 2.5,
        "booking": {"share_code": "VALID1", "status": "active",
                    "booking_status": "FULL", "readback_validation": "PASSED"},
    }
    monkeypatch.setattr(editor, "list_published", lambda day: {"rollover": record})
    monkeypatch.setattr(booking, "booking_lifecycle", lambda rec, games: rec)
    official = {"rollover": {"selected": True, "games": [
        {"match_id": "published:other"}], "chain": [{
            "date": "2026-10-14", "picks": [{"match_id": "published:other"}],
        }]}}
    assert editor.overlay_on_card("2026-10-14", official) == official
    manual = {"rollover": {"selected": True, "games": [], "chain": [{
        "date": "2026-10-14", "picks": [{
            "sportybet_event_id": "52588", "editorial_manual": True,
        }],
    }], "challenge_status": "active", "target_days": 3}}
    displayed = editor.overlay_on_card("2026-10-14", manual)["rollover"]
    assert displayed["editorial_manual"] is True
    assert displayed["source"] == "admin_curated"
    assert displayed["booking_code"] == "VALID1"
    assert displayed["target_days"] == 3
    assert len(displayed["chain"]) == 1
    assert displayed["hit_probability"] is None
    assert displayed["model_probability_available"] is not True


def test_manual_rollover_reports_repeat_without_a_hard_failure():
    manual = [{"sportybet_event_id": "52587", "match_id": "sportybet:52587",
               "home_team": "Arsenal", "away_team": "Lille"}]
    warnings = editor._check_exposure(
        manual, {"2_odds": {"selected": True, "games": manual}},
        {}, {}, tier="rollover",
    )
    assert len(warnings) == 1
    assert warnings[0]["also_in_tiers"] == ["2_odds"]


def _manual_rollover_publish_db(monkeypatch, prior_status=None):
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool
    from leagues import sportybet, booking, picks_db
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE daily_cards (publish_date VARCHAR(10), payload TEXT)"))
        conn.execute(text("""
            CREATE TABLE wc_rollover_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chain_start_date VARCHAR(10),
                day_number INTEGER, date VARCHAR(10), picks TEXT, combined_odds FLOAT,
                avg_confidence FLOAT, status VARCHAR(20), policy_version VARCHAR(40),
                created_at DATETIME, updated_at DATETIME)
        """))
        if prior_status:
            conn.execute(text("""
                INSERT INTO wc_rollover_days
                (chain_start_date,day_number,date,picks,combined_odds,
                 avg_confidence,status,policy_version)
                VALUES ('2026-10-13',1,'2026-10-13','[]',2.25,0.7,:status,'TEST')
            """), {"status": prior_status})
    games = [{
        "match_id": "sportybet:52587", "sportybet_event_id": "52587",
        "home_team": "Arsenal", "away_team": "Lille", "market": "over_1_5",
        "prediction": "Over 1.5", "prediction_type": "goals",
        "kickoff": "2026-10-14T19:00:00+00:00",
        "league": "Test League", "odds": 2.4,
    }]
    monkeypatch.setattr(editor, "_engine", lambda: engine)
    monkeypatch.setattr(editor, "preview", lambda *args, **kwargs: {
        "date": "2026-10-14", "games": games,
    })
    monkeypatch.setattr(editor, "_current_bookable_games",
                        lambda *args, **kwargs: games)
    monkeypatch.setattr(editor, "list_published", lambda day: {})
    monkeypatch.setattr(sportybet, "fetch_board", lambda **kwargs: {"test": True})
    monkeypatch.setattr(picks_db, "load_card", lambda day: {})
    monkeypatch.setattr(booking, "bookings_for", lambda day: {})
    monkeypatch.setattr(booking, "create_booking", lambda *args, **kwargs: {
        "status": "active", "booking_status": "FULL",
        "share_code": "TESTCODE", "readback_validation": "PASSED",
        "actual_sportybet_odds": 2.4, "final_booked_legs": games,
    })
    return engine


def test_manual_rollover_publishes_one_atomic_booked_chain_stage(monkeypatch):
    from sqlalchemy import text
    db = _manual_rollover_publish_db(monkeypatch)
    result = editor.publish("rollover", "52587,over_1_5")
    assert result["status"] == "PUBLISHED"
    assert result["share_code"] == "TESTCODE"
    with db.connect() as conn:
        days = conn.execute(text(
            "SELECT chain_start_date,day_number,date,picks,status "
            "FROM wc_rollover_days"
        )).all()
        manual = conn.execute(text(
            "SELECT tier,detail FROM editorial_tier_slips"
        )).all()
    assert len(days) == len(manual) == 1
    assert days[0][0:3] == ("2026-10-14", 1, "2026-10-14")
    assert days[0][4] == "pending"
    assert manual[0][0] == "rollover"
    import json
    picks = json.loads(days[0][3])
    assert picks[0]["market_key"] == "over_1_5"
    assert picks[0]["confidence"] is None
    with pytest.raises(ValueError, match="published in another session"):
        editor.publish("rollover", "52587,over_1_5")


def test_manual_rollover_advances_only_after_verified_previous_win(monkeypatch):
    from sqlalchemy import text
    db = _manual_rollover_publish_db(monkeypatch, prior_status="won")
    result = editor.publish("rollover", "52587,over_1_5")
    assert result["status"] == "PUBLISHED"
    with db.connect() as conn:
        rows = conn.execute(text(
            "SELECT chain_start_date,day_number,date FROM wc_rollover_days "
            "ORDER BY day_number"
        )).all()
    assert rows[1] == ("2026-10-13", 2, "2026-10-14")


def test_manual_rollover_rejects_pending_prior_without_orphan_record(monkeypatch):
    from sqlalchemy import text
    db = _manual_rollover_publish_db(monkeypatch, prior_status="pending")
    with pytest.raises(ValueError, match="blocked"):
        editor.publish("rollover", "52587,over_1_5")
    with db.connect() as conn:
        manual = conn.execute(text(
            "SELECT count(*) FROM editorial_tier_slips"
        )).scalar()
        days = conn.execute(text(
            "SELECT count(*) FROM wc_rollover_days"
        )).scalar()
    assert manual == 0
    assert days == 1


def test_growth_telegram_does_not_invent_model_probabilities_for_manual_rollover():
    from growth.dataset import _rollover_block
    from growth.templates import rollover as format_rollover
    today = "2026-10-14"
    day = {
        "day_number": 1, "date": today, "status": "pending",
        "editorial_manual": True,
        "picks": [{
            "match_id": "sportybet:52587", "home_team": "Arsenal",
            "away_team": "Lille", "league": "Football",
            "commence_time": "2026-10-14T20:00:00+00:00",
            "prediction": "Over 1.5", "market_key": "over_1_5",
            "odds": 2.4, "confidence": None, "editorial_manual": True,
        }],
    }
    tier = _rollover_block({
        "chain": [day], "games": [], "total_odds": 2.4,
        "target_days": 3, "chain_length": 1,
        "today_hit_probability": None, "editorial_manual": True,
    }, today)
    assert tier["editorial_manual"] is True
    assert tier["hit_probability"] is None
    assert tier["legs"][0]["confidence"] is None
    assert tier["legs"][0]["model_probability_available"] is False
    message = format_rollover({"date": today, "rollover": tier}, "telegram")
    assert "Admin-curated" in message["text"]
    assert "0%" not in message["text"]
    assert "lands about" not in message["text"]


def test_manual_chain_stage_rehydrates_public_card_with_market_key(monkeypatch):
    from leagues import daily_feed, rollover_db
    item = {
        "day_number": 1, "date": "2026-10-14", "status": "pending",
        "combined_odds": 2.4, "hit_probability": None,
        "editorial_manual": True,
        "picks": [{
            "match_id": "sportybet:52587", "sportybet_event_id": "52587",
            "home_team": "Arsenal", "away_team": "Lille",
            "league": "Test League", "commence_time": "2026-10-14T20:00:00+00:00",
            "prediction": "Over 1.5", "market": "goals",
            "market_key": "over_1_5", "odds": 2.4,
            "odds_are_real": True, "bookable": True,
            "editorial_manual": True, "confidence": None,
        }],
    }
    monkeypatch.setattr(rollover_db, "load_chain", lambda day: {
        "start_date": "2026-10-14", "days": [item], "status": "active",
    })
    card = daily_feed._build_rollover([], "2026-10-14")
    assert card["selected"] is True
    assert card["editorial_manual"] is True
    assert card["source"] == "admin_curated"
    assert card["total_odds"] == 2.4
    assert card["today_hit_probability"] is None
    assert card["games"][0]["market"] == "over_1_5"
    assert card["games"][0]["confidence"] is None
    assert card["games"][0]["editorial_manual"] is True



def test_explicit_2_5_10_replacement_requires_opt_in_and_preserves_original(monkeypatch):
    from leagues import sportybet, picks_db, booking
    now = datetime(2026, 10, 17, 9, tzinfo=timezone.utc)
    board = fake_board(now)
    original = {"2_odds": {"selected": True, "games": [
        {"match_id": "official-original", "sportybet_event_id": "9876"},
    ]}}
    monkeypatch.setattr(picks_db, "load_card", lambda day: original)
    monkeypatch.setattr(booking, "bookings_for", lambda day: {})
    monkeypatch.setattr(editor, "list_published", lambda day: {})
    monkeypatch.setattr(sportybet, "availability_for",
                        lambda board, home, away, kickoff, league, market, event_id=None:
                        {"sportybet_available": True,
                         "sportybet_odds": 2.4, "event_id": event_id})
    with pytest.raises(ValueError, match="immutable official"):
        editor.preview("2_odds", "52588,home_win", board=board, now=now)
    checked = editor.preview(
        "2_odds", "52588,home_win", board=board, now=now,
        replace_official_display=True,
    )
    assert checked["replaces_official_display"] is True
    assert checked["original_official_record_preserved"] is True
    assert original["2_odds"]["games"][0]["match_id"] == "official-original"


@pytest.mark.parametrize("tier", ["banker", "rollover"])
def test_nonreplaceable_tiers_fail_closed(tier):
    with pytest.raises(ValueError, match="Only 2, 5, 10"):
        editor._official_display_replacement(tier, explicit=True)


@pytest.mark.parametrize("tier", ["2_odds", "5_odds", "10_odds"])
def test_display_override_is_explicit_separate_from_original_model(monkeypatch, tier):
    from leagues import booking
    original = {
        "selected": True,
        "games": [{"match_id": "model-original"}],
        "booking": {"share_code": "OLDMODEL"},
        "confidence": .85,
    }
    new = {
        "games": [{"match_id": "sportybet:52588",
                   "sportybet_event_id": "52588"}],
        "total_odds": 11.846,
        "booking": {"status": "active", "booking_status": "FULL",
                    "share_code": "NEWCODE", "readback_validation": "PASSED"},
        "replaces_official_display": True,
        "model_probability_available": False,
    }
    monkeypatch.setattr(editor, "list_published", lambda day: {tier:new})
    monkeypatch.setattr(booking, "booking_lifecycle",
                        lambda b, games: {**b,"actionable":True})
    display = editor.overlay_on_card("2026-10-17", {tier:original})[tier]
    assert display["booking_code"] == "NEWCODE"
    assert display["original_official_booking_code"] == "OLDMODEL"
    assert display["replaces_official_display"] is True
    assert display["model_probability_available"] is False
    assert original["games"] == [{"match_id":"model-original"}]


def test_original_tier_and_other_tier_reuse_are_allowed_with_provenance():
    same = {"sportybet_event_id": "52588", "match_id": "sportybet:52588",
            "home_team": "Atletico", "away_team": "Man United"}
    assert editor._check_exposure(
        [same], {"2_odds":{"selected":True,"games":[same]}}, {},
        {}, tier="2_odds",
    ) == []  # original selected ticket will settle separately
    found = editor._check_exposure(
        [same], {"5_odds":{"selected":True,"games":[same]}}, {},
        {}, tier="2_odds",
    )
    assert len(found) == 1 and found[0]["also_in_tiers"] == ["5_odds"]
    assert found[0]["sportybet_event_id"] == "52588"


def test_manual_accepts_imported_2_odds_feyenoord_fixture_also_on_model_10_odds():
    """Regression for Saturday's V4SUNZ import: no false invalid-game error."""
    imported = [
        {"sportybet_event_id": "sr:match:72041178",
         "match_id": "sportybet:sr:match:72041178",
         "home_team": "SC Telstar", "away_team": "Feyenoord"},
        {"sportybet_event_id": "sr:match:72341280",
         "match_id": "sportybet:sr:match:72341280",
         "home_team": "Stockport", "away_team": "Bromley"},
        {"sportybet_event_id": "sr:match:72041182",
         "match_id": "sportybet:sr:match:72041182",
         "home_team": "ADO Den Haag", "away_team": "PSV Eindhoven"},
    ]
    model = {"10_odds": {"selected": True, "games": [{
        "match_id": "sportybet:sr:match:72041178",
    }]}}
    warnings = editor._check_exposure(imported, model, {}, {}, tier="2_odds")
    assert len(warnings) == 1
    assert warnings[0]["fixture"] == "SC Telstar vs Feyenoord"
    assert warnings[0]["also_in_tiers"] == ["10_odds"]


def test_manual_reuse_across_multiple_manually_published_tiers():
    same = {"sportybet_event_id": "sr:match:72041178",
            "match_id": "sportybet:sr:match:72041178",
            "home_team": "SC Telstar", "away_team": "Feyenoord"}
    manual = {
        "5_odds": {"games": [same]},
        "10_odds": {"games": [same]},
    }
    warnings = editor._check_exposure([same], {}, {}, manual, tier="2_odds")
    assert len(warnings) == 1
    assert warnings[0]["also_in_tiers"] == ["10_odds", "5_odds"]


def test_manual_always_rejects_duplicate_match_within_one_ticket():
    same = {"sportybet_event_id": "12345", "match_id": "sportybet:12345",
            "home_team": "Test", "away_team": "Test 2"}
    with pytest.raises(ValueError, match="Fixture repeated"):
        editor._check_exposure([same, same], {}, {}, {}, tier="2_odds")
    with pytest.raises(ValueError, match="fixture repeated"):
        editor.parse_input("12345,home_win\n12345,away_win", "2_odds")


def test_identifier_aliases_match_bookmaker_event_keys_only():
    game = {"sportybet_event_id": "sr:match:3",
            "match_id": "sportybet:sr:match:3",
            "home_team": "Home", "away_team": "Away"}
    other = {"match_id": "sportybet:sr:match:3"}
    assert editor._check_exposure(
        [game], {"10_odds":{"selected":True,"games":[other]}}, {},
        {}, tier="2_odds",
    )[0]["also_in_tiers"] == ["10_odds"]




def test_manual_booker_uses_single_fresh_board_for_preview_and_repricing(monkeypatch):
    from leagues import sportybet
    calls = []
    board = {"__meta__": {"ready": True}}
    def fetch_board(*, force=False):
        assert force is True
        calls.append(force)
        return board
    monkeypatch.setattr(sportybet, "fetch_board", fetch_board)
    def preview(tier, lines, **kwargs):
        assert tier == "2_odds"
        assert kwargs["board"] is board
        raise RuntimeError("stopped after initial validation")
    monkeypatch.setattr(editor, "preview", preview)
    with pytest.raises(RuntimeError, match="stopped after initial validation"):
        editor.publish("2_odds", "52588,home_win",
                       replace_official_display=True)
    assert len(calls) == 1


def test_curated_manual_preserves_verified_country_tournament_identity(monkeypatch):
    from leagues import sportybet
    now = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    board = fake_board(now)
    entry = board["sports"][0]
    entry.update({
        "competition": "Premier League",
        "sportybet_tournament_id": "sr:tournament:17",
        "sportybet_category_id": "sr:category:1",
        "sportybet_category": "England",
        "sportybet_country": "England",
    })
    monkeypatch.setattr(sportybet, "availability_for",
                        lambda *args, **kwargs: {
                            "sportybet_available": True, "sportybet_odds": 1.3})
    row = editor._current_bookable_games(
        [("52587", "home_win")], board, now=now, date="2026-10-13")[0]
    assert row["sportybet_event_id"] == "52587"
    assert row["league"] == "Premier League"
    assert row["league_slug"] == "eng.1"
    assert row["competition_country"] == "England"
    assert row["sportybet_tournament_id"] == "sr:tournament:17"
    assert row["sportybet_category_id"] == "sr:category:1"
    assert row["sportybet_country"] == "England"
    assert row["competition_identity_basis"] == "sportybet_provider_ids"
    assert row["settlement_source_candidates"] == ["espn"]
    assert row["score_competition_mapped"] is True


def test_manual_unknown_country_identity_never_falls_back_to_english_league(monkeypatch):
    from leagues import sportybet
    now = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    board = fake_board(now)
    board["sports"][0].update({
        "competition": "Premier League",
        "sportybet_tournament_id": "sr:tournament:999999",
        "sportybet_category_id": "sr:category:123456",
        "sportybet_country": "Singapore",
    })
    monkeypatch.setattr(sportybet, "availability_for",
                        lambda *args, **kwargs: {
                            "sportybet_available": True, "sportybet_odds": 1.3})
    row = editor._current_bookable_games(
        [("52587", "home_win")], board, now=now, date="2026-10-13")[0]
    assert row["sportybet_country"] == "Singapore"
    assert row["competition_identity_basis"] == "unknown_provider_ids"
    assert row.get("league_slug") is None
    assert row["score_competition_mapped"] is False
    assert row["settlement_source_candidates"] == []


def test_manual_league_name_without_identity_only_accepts_unique_known_competition(monkeypatch):
    from leagues import sportybet
    now = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    board = fake_board(now)
    board["sports"][0]["competition"] = "UEFA Europa League"
    monkeypatch.setattr(sportybet, "availability_for",
                        lambda *args, **kwargs: {
                            "sportybet_available": True, "sportybet_odds": 1.3})
    row = editor._current_bookable_games(
        [("52587", "home_win")], board, now=now, date="2026-10-13")[0]
    assert row["league_slug"] == "uefa.europa"
    assert set(row["settlement_source_candidates"]) == {"espn", "openligadb"}
