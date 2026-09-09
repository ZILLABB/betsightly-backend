import asyncio

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from leagues import api, picks_db
from leagues.booking import leg_fingerprint


def _leg(status, odds=1.5):
    return {"status": status, "odds": odds}


def _slip(category, status, picks, presentation="accumulator", odds=2.0):
    return {
        "date": "2026-09-08",
        "category": category,
        "status": status,
        "presentation": presentation,
        "total_odds": odds,
        "picks": picks,
    }


def test_performance_summary_counts_current_and_legacy_over_1_5_as_picks(monkeypatch):
    history = [
        _slip("over_1_5", "won", [_leg("won"), _leg("lost")], "singles"),
        _slip("over_1_5", "lost", [_leg("won"), _leg("lost")]),
        _slip("2_odds", "won", [_leg("won"), _leg("won")], odds=2.1),
        _slip("5_odds", "lost", [_leg("won"), _leg("lost")], odds=5.2),
    ]
    monkeypatch.setattr(picks_db, "get_history", lambda limit_days: history)

    summary = picks_db.performance_summary(limit_days=60)

    assert summary["over_1_5"]["unit"] == "pick"
    assert summary["over_1_5"]["won"] == 2
    assert summary["over_1_5"]["lost"] == 2
    assert summary["over_1_5"]["settled"] == 4
    assert summary["2_odds"]["unit"] == "slip"
    assert summary["2_odds"]["won"] == 1
    assert summary["5_odds"]["lost"] == 1


def test_results_totals_keep_singles_and_rollover_separate(monkeypatch):
    history = [
        _slip("over_1_5", "won", [_leg("won"), _leg("lost")]),
        _slip("2_odds", "won", [_leg("won")], odds=2.1),
        _slip("5_odds", "lost", [_leg("lost")], odds=5.2),
    ]
    monkeypatch.setattr(picks_db, "get_history", lambda limit_days, category=None: history)
    monkeypatch.setattr(
        picks_db,
        "performance_summary",
        lambda limit_days: {
            "over_1_5": {"unit": "pick", "won": 1, "lost": 1, "settled": 2,
                           "staked": 2.0, "returned": 1.5},
            "2_odds": {"unit": "slip", "won": 1, "lost": 0, "settled": 1,
                       "staked": 1.0, "returned": 2.1},
            "5_odds": {"unit": "slip", "won": 0, "lost": 1, "settled": 1,
                       "staked": 1.0, "returned": 0.0},
        },
    )
    from leagues import rollover_db
    monkeypatch.setattr(
        rollover_db,
        "history",
        lambda limit_days: [{"date": "2026-09-08", "status": "won"}],
    )

    result = asyncio.run(api.get_results(days=60))

    assert result["totals"]["slips"]["settled"] == 2
    assert result["totals"]["slips"]["settled"] == (
        result["totals"]["slips"]["won"] + result["totals"]["slips"]["lost"]
    )
    assert result["totals"]["picks"]["settled"] == 2
    assert result["totals"]["picks"]["settled"] == (
        result["totals"]["picks"]["won"] + result["totals"]["picks"]["lost"]
    )
    assert len(result["rollover_history"]) == 1
    assert result["totals"]["slips"]["settled"] != 3


def test_published_slips_migration_and_new_rows_include_policy_version(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE published_slips ("
            "id INTEGER PRIMARY KEY, date VARCHAR(10), category VARCHAR(20), "
            "picks TEXT, total_odds FLOAT, hit_probability FLOAT, "
            "presentation VARCHAR(16), status VARCHAR(20), settled_at DATETIME, "
            "created_at DATETIME, updated_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO published_slips "
            "(id, date, category, picks, total_odds, hit_probability, "
            "presentation, status) VALUES "
            "(1, '2026-09-08', '2_odds', '[]', 2.0, 0.5, "
            "'accumulator', 'lost')"
        )

    picks_db._add_missing_columns(engine)
    assert "policy_version" in {
        column["name"] for column in inspect(engine).get_columns("published_slips")
    }

    test_session = sessionmaker(bind=engine)
    monkeypatch.setattr(picks_db, "SessionLocal", test_session)
    assert picks_db.archive_slip(
        "2026-09-09",
        "2_odds",
        [{"match_id": "m1", "status": "pending"}],
        2.1,
        0.6,
    )
    row = (
        test_session().query(picks_db.PublishedSlip)
        .filter(picks_db.PublishedSlip.date == "2026-09-09")
        .one()
    )
    assert row.policy_version == picks_db.PUBLISHED_POLICY_VERSION
    history = picks_db.get_history(limit_days=2)
    assert history[0]["policy_version"] == "selection-policy-v1.1"
    assert history[1]["policy_version"] is None


def test_settled_accumulator_return_uses_winning_odds_and_voids_at_one():
    cases = [
        ({"status": "won", "total_odds": 9.0,
          "picks": [_leg("won", 1.5), _leg("won", 2.0)]}, 3.0),
        ({"status": "won", "total_odds": 9.0,
          "picks": [_leg("won", 1.5), _leg("void", 1.8)]}, 1.5),
        ({"status": "won", "total_odds": 8.02,
          "picks": [_leg("won", 1.65), _leg("void", 1.27),
                    _leg("void", 1.29), _leg("won", 1.77)]}, 2.9205),
        ({"status": "lost", "total_odds": 8.02,
          "picks": [_leg("won", 1.65), _leg("lost", 1.77)]}, 0.0),
        ({"status": "void", "total_odds": 2.0,
          "picks": [_leg("void", 2.0)]}, 1.0),
        ({"status": "won", "total_odds": 2.4,
          "picks": [{"status": "void", "market": "dnb_home", "odds": 1.7},
                    _leg("won", 1.4)]}, 1.4),
    ]
    for slip, expected in cases:
        returned, source = picks_db.settled_accumulator_return(slip)
        assert returned == expected
        assert source == "settled_leg_odds" or slip["status"] != "won"


def test_settled_accumulator_return_has_explicit_legacy_fallback():
    returned, source = picks_db.settled_accumulator_return({
        "status": "won", "total_odds": 4.2,
        "picks": [{"status": None, "odds": 1.5}],
    })
    assert returned == 4.2
    assert source == "legacy_total_odds"


def test_performance_uses_void_adjusted_return_and_labels_bookable_coverage(monkeypatch):
    picks = [_leg("won", 1.65), _leg("void", 1.27), _leg("won", 1.77)]
    for index, pick in enumerate(picks):
        pick.update({"match_id": f"m{index}", "market": "over_1_5",
                     "home_team": f"H{index}", "away_team": f"A{index}",
                     "odds_are_real": True})
    history = [_slip("10_odds", "won", picks, odds=8.02)]
    monkeypatch.setattr(picks_db, "get_history", lambda limit_days: history)
    monkeypatch.setattr(picks_db, "_booking_records", lambda cutoff: {})
    result = picks_db.performance_summary(90)["10_odds"]
    assert result["returned"] == 2.9205
    assert result["profit"] == 1.92
    assert result["published_odds_roi"] == 1.9205
    assert result["published_record"]["return_sources"] == {
        "settled_leg_odds": 1
    }
    assert result["bookable_record"]["settled"] == 0
    assert result["bookable_record"]["coverage"] == 0.0


def test_bookable_roi_requires_validated_exact_selection(monkeypatch):
    picks = []
    for index, odds in enumerate((1.5, 1.4)):
        picks.append({"match_id": f"m{index}", "market": "over_1_5",
                      "home_team": f"H{index}", "away_team": f"A{index}",
                      "status": "won", "odds": odds, "odds_are_real": True})
    slip = _slip("2_odds", "won", picks, odds=2.1)
    fingerprint = leg_fingerprint(picks)
    monkeypatch.setattr(picks_db, "get_history", lambda limit_days: [slip])
    monkeypatch.setattr(picks_db, "_booking_records", lambda cutoff: {
        (slip["date"], slip["category"]): {
            "status": "active", "readback_validation": "PASSED",
            "actual_sportybet_odds": 2.2, "leg_fingerprint": fingerprint,
            "booking_variant_fingerprint": fingerprint, "booked_leg_count": 2,
        }
    })
    result = picks_db.performance_summary(90)["2_odds"]
    assert result["bookable_record"] == {
        "settled": 1, "won": 1, "lost": 0, "staked": 1.0,
        "returned": 2.2, "profit": 1.2, "roi": 1.2, "coverage": 1.0,
    }


def test_get_history_uses_true_calendar_window_without_per_day_row_cap(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    picks_db.PublishedSlip.__table__.create(engine)
    session = sessionmaker(bind=engine)
    db = session()
    for index in range(8):
        db.add(picks_db.PublishedSlip(
            date="2026-09-09", category=f"tier_{index}", picks="[]",
            total_odds=2.0, hit_probability=0.5, status="lost",
        ))
    db.add(picks_db.PublishedSlip(
        date="2026-08-11", category="boundary", picks="[]",
        total_odds=2.0, hit_probability=0.5, status="lost",
    ))
    db.add(picks_db.PublishedSlip(
        date="2026-08-10", category="too_old", picks="[]",
        total_odds=2.0, hit_probability=0.5, status="lost",
    ))
    db.commit()
    db.close()
    monkeypatch.setattr(picks_db, "SessionLocal", session)

    rows = picks_db.get_history(limit_days=30, as_of="2026-09-09")
    assert len(rows) == 9
    assert {row["category"] for row in rows} >= {"tier_7", "boundary"}
    assert "too_old" not in {row["category"] for row in rows}
    assert picks_db.history_cutoff(60, "2026-09-09") == "2026-07-12"
    assert picks_db.history_cutoff(90, "2026-09-09") == "2026-06-12"
