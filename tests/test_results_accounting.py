import asyncio

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from leagues import api, picks_db


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
    assert history[0]["policy_version"] == "fixture-ranked-v1.1"
    assert history[1]["policy_version"] is None
