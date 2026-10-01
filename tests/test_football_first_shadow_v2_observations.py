from datetime import (
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy import (
    create_engine,
    func,
    select,
)

from leagues import (
    football_first_shadow_observations
    as shared,
)
from leagues import (
    football_first_shadow_v2_observations
    as v2obs,
)


def _db():
    db = create_engine(
        "sqlite:///:memory:"
    )

    shared.ensure_table(
        db
    )

    return db


def _fixture():
    return {
        "event_id":
            "same-fixture",
        "commence_time":
            (
                datetime.now(
                    timezone.utc
                )
                + timedelta(
                    hours=5
                )
            ).isoformat(),
        "league_slug":
            "eng.1",
        "league":
            "Premier League",
        "home": {
            "name":
                "Home",
        },
        "away": {
            "name":
                "Away",
        },
    }


def _champion():
    return {
        "probabilities": {
            "away_win":
                .25,
            "draw":
                .25,
            "home_win":
                .50,
        }
    }


def _challenger(
    version,
):
    return {
        "status":
            "READY",
        "model_version":
            version,
        "feature_version":
            "test-features",
        "probabilities": {
            "away_win":
                .20,
            "draw":
                .25,
            "home_win":
                .55,
        },
        "feature_evidence": {
            "home_history":
                10,
            "away_history":
                10,
        },
    }


def test_v1_and_v2_same_fixture_have_separate_keys():
    fixture = _fixture()

    now = datetime.now(
        timezone.utc
    )

    v1, _ = shared.build_observation(
        fixture,
        _champion(),
        _challenger(
            "shadow-v1"
        ),
        observed_at=now,
    )

    v2, _ = shared.build_observation(
        fixture,
        _champion(),
        _challenger(
            "shadow-v2"
        ),
        observed_at=now,
    )

    assert (
        v1[
            "observation_key"
        ]
        != v2[
            "observation_key"
        ]
    )


def test_v2_first_write_is_immutable():
    db = _db()

    fixture = _fixture()

    row, reason = (
        shared.build_observation(
            fixture,
            _champion(),
            _challenger(
                "shadow-v2"
            ),
            observed_at=datetime.now(
                timezone.utc
            ),
        )
    )

    assert reason == "ready"

    first = v2obs._persist(
        row,
        db_engine=db,
    )

    second = v2obs._persist(
        row,
        db_engine=db,
    )

    assert (
        first[
            "status"
        ]
        == "RECORDED"
    )

    assert (
        second[
            "status"
        ]
        == "EXISTS"
    )

    with db.begin() as conn:
        count = conn.execute(
            select(
                func.count()
            )
            .select_from(
                shared.observations
            )
        ).scalar_one()

    assert count == 1
