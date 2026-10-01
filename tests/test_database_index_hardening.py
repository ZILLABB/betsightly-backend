import logging

from sqlalchemy import (
    create_engine,
    inspect,
    text,
)

import database
from utils import (
    database_optimization
    as dbopt,
)


def test_database_indexes_skip_missing_legacy_schema_cleanly(
    monkeypatch,
    caplog,
):
    db = create_engine(
        "sqlite:///:memory:"
    )

    with db.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE predictions (
                    id INTEGER PRIMARY KEY,
                    fixture_id INTEGER,
                    created_at DATETIME
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE fixtures (
                    id INTEGER PRIMARY KEY,
                    date DATETIME,
                    league_id INTEGER
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE betting_codes (
                    id INTEGER PRIMARY KEY,
                    punter_id INTEGER,
                    bookmaker_id INTEGER,
                    featured BOOLEAN,
                    created_at DATETIME
                )
                """
            )
        )

    monkeypatch.setattr(
        database,
        "engine",
        db,
    )

    caplog.set_level(
        logging.INFO,
        logger="utils.database_optimization",
    )

    dbopt.create_database_indexes()

    inspector = inspect(
        db
    )

    prediction_indexes = {
        row[
            "name"
        ]
        for row
        in inspector.get_indexes(
            "predictions"
        )
    }

    fixture_indexes = {
        row[
            "name"
        ]
        for row
        in inspector.get_indexes(
            "fixtures"
        )
    }

    betting_indexes = {
        row[
            "name"
        ]
        for row
        in inspector.get_indexes(
            "betting_codes"
        )
    }

    assert (
        "idx_predictions_fixture_id"
        in prediction_indexes
    )

    assert (
        "idx_predictions_created_at"
        in prediction_indexes
    )

    assert (
        "idx_predictions_category"
        not in prediction_indexes
    )

    assert (
        "idx_predictions_fixture_category"
        not in prediction_indexes
    )

    assert (
        "idx_fixtures_date"
        in fixture_indexes
    )

    assert (
        "idx_fixtures_league_id"
        in fixture_indexes
    )

    assert (
        "idx_fixtures_status"
        not in fixture_indexes
    )

    assert (
        "idx_betting_codes_punter_id"
        in betting_indexes
    )

    assert (
        "idx_betting_codes_bookmaker_id"
        in betting_indexes
    )

    messages = [
        record.getMessage()
        for record
        in caplog.records
    ]

    assert any(
        (
            "prediction_combinations"
            in message
            and "does not exist"
            in message
        )
        for message
        in messages
    )

    assert not any(
        (
            "UndefinedColumn"
            in message
            or "UndefinedTable"
            in message
        )
        for message
        in messages
    )
