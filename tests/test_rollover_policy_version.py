from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from leagues import rollover_db
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION


def test_rollover_migration_preserves_old_and_versions_new_rows(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE wc_rollover_days ("
            "id INTEGER PRIMARY KEY, chain_start_date VARCHAR(10) NOT NULL, "
            "day_number INTEGER NOT NULL, date VARCHAR(10) NOT NULL, "
            "picks TEXT NOT NULL, combined_odds FLOAT NOT NULL, "
            "avg_confidence FLOAT NOT NULL, status VARCHAR(20), "
            "created_at DATETIME, updated_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO wc_rollover_days "
            "(id, chain_start_date, day_number, date, picks, combined_odds, "
            "avg_confidence, status) VALUES "
            "(1, '2026-09-01', 1, '2026-09-01', '[]', 2.0, .5, 'lost')"
        )

    monkeypatch.setattr("database.engine", engine)
    monkeypatch.setattr(rollover_db, "SessionLocal", sessionmaker(bind=engine))
    rollover_db.ensure_table()
    assert "policy_version" in {
        column["name"]
        for column in inspect(engine).get_columns("wc_rollover_days")
    }
    assert rollover_db.append_day("2026-09-02", {
        "day_number": 1, "date": "2026-09-02", "picks": [],
        "combined_odds": 2.1, "hit_probability": .48,
    })

    session = sessionmaker(bind=engine)()
    rows = session.query(rollover_db.RolloverDay).order_by(
        rollover_db.RolloverDay.id
    ).all()
    assert rows[0].policy_version is None
    assert rows[1].policy_version == PUBLISHED_SELECTION_POLICY_VERSION
    assert rollover_db._day_dict(rows[1])["policy_version"] == (
        PUBLISHED_SELECTION_POLICY_VERSION
    )
    session.close()
