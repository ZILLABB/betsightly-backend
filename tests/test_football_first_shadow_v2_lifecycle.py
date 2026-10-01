from datetime import (
    datetime,
    timedelta,
    timezone,
)
import uuid

import pytest
from sqlalchemy import (
    create_engine,
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
from leagues import results_checker


def _db():
    db = create_engine(
        "sqlite:///:memory:"
    )

    shared.ensure_table(
        db
    )

    return db


def _patch_v2_model(
    monkeypatch,
):
    monkeypatch.setattr(
        v2obs.shadow_v2,
        "status",
        lambda: {
            "model_version":
                "shadow-v2",

            "feature_version":
                "v2-features",

            "feature_count":
                32,

            "eligible_league_ids": [
                39,
                71,
                128,
                141,
                253,
            ],

            "shadow_only":
                True,

            "automatic_promotion":
                False,
        },
    )

    monkeypatch.setattr(
        v2obs,
        "collection_allowed",
        lambda: (
            True,
            "enabled",
        ),
    )


def _fixture(
    event_id,
    kickoff,
):
    return {
        "event_id":
            event_id,

        "commence_time":
            kickoff.isoformat(),

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
            "features",

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


def test_v2_review_packet_starts_at_zero_and_never_promotes(
    monkeypatch,
):
    db = _db()

    _patch_v2_model(
        monkeypatch
    )

    packet = v2obs.review_packet(
        db_engine=db
    )

    assert (
        packet[
            "review_gate"
        ][
            "eligible"
        ]
        is False
    )

    assert (
        packet[
            "review_gate"
        ][
            "current_settled"
        ]
        == 0
    )

    assert (
        packet[
            "review_gate"
        ][
            "remaining_to_minimum"
        ]
        == 300
    )

    assert (
        packet[
            "promotion_effective"
        ]
        is False
    )

    assert (
        packet[
            "automatic_promotion"
        ]
        is False
    )

    assert (
        packet[
            "evidence"
        ][
            "v1_evidence_counts_toward_v2_threshold"
        ]
        is False
    )


def test_v2_approval_fails_closed_before_300_gate(
    monkeypatch,
):
    db = _db()

    _patch_v2_model(
        monkeypatch
    )

    with pytest.raises(
        ValueError,
        match="promotion_review_gate_not_met",
    ):
        v2obs.record_review(
            "APPROVE_FOR_PROMOTION_IMPLEMENTATION",
            reviewer="tester",
            db_engine=db,
        )


def test_v2_keep_champion_review_is_model_version_isolated(
    monkeypatch,
):
    db = _db()

    _patch_v2_model(
        monkeypatch
    )

    result = v2obs.record_review(
        "KEEP_CHAMPION",
        reviewer="tester",
        note="continue prospective collection",
        db_engine=db,
    )

    assert (
        result[
            "status"
        ]
        == "RECORDED"
    )

    assert (
        result[
            "review"
        ][
            "model_version"
        ]
        == "shadow-v2"
    )

    # Write a newer V1 review.  V2 lookup must still return
    # only the V2 decision.
    with db.begin() as conn:
        conn.execute(
            shared.reviews
            .insert()
            .values(
                review_id=str(
                    uuid.uuid4()
                ),

                model_version=
                    "shadow-v1",

                evidence_n=
                    999,

                evidence_status=
                    "ELIGIBLE_FOR_HUMAN_REVIEW",

                decision=
                    "KEEP_CHAMPION",

                reviewer=
                    "v1-reviewer",

                note=
                    None,

                created_at=
                    datetime.now(
                        timezone.utc
                    )
                    + timedelta(
                        seconds=1
                    ),
            )
        )

    latest_v2 = (
        v2obs.latest_review(
            db_engine=db
        )
    )

    latest_v1 = (
        shared.latest_review(
            model_version=
                "shadow-v1",
            db_engine=db,
        )
    )

    assert (
        latest_v2[
            "model_version"
        ]
        == "shadow-v2"
    )

    assert (
        latest_v1[
            "model_version"
        ]
        == "shadow-v1"
    )

    assert (
        result[
            "promotion_effective"
        ]
        is False
    )


def test_shared_settlement_can_target_only_v2_model_version(
    monkeypatch,
):
    db = _db()

    now = datetime.now(
        timezone.utc
    )

    kickoff = (
        now
        - timedelta(
            hours=5
        )
    )

    observed = (
        now
        - timedelta(
            hours=8
        )
    )

    fixture = _fixture(
        "shared-fixture",
        kickoff,
    )

    rows = []

    for version in (
        "shadow-v1",
        "shadow-v2",
    ):
        row, reason = (
            shared.build_observation(
                fixture,
                _champion(),
                _challenger(
                    version
                ),
                observed_at=observed,
            )
        )

        assert reason == "ready"

        rows.append(
            row
        )

    with db.begin() as conn:
        for row in rows:
            conn.execute(
                shared.observations
                .insert()
                .values(
                    **row
                )
            )

    monkeypatch.setattr(
        results_checker,
        "_collect_scores_for_picks",
        lambda *args, **kwargs: (
            {},
            "test",
        ),
    )

    monkeypatch.setattr(
        results_checker,
        "_lookup_settlement_score",
        lambda *args, **kwargs: {
            "home_score":
                2,

            "away_score":
                1,
        },
    )

    result = (
        shared
        .settle_pending_observations(
            now=now,
            model_version=
                "shadow-v2",
            db_engine=db,
        )
    )

    assert (
        result[
            "settled"
        ]
        == 1
    )

    with db.begin() as conn:
        stored = [
            dict(
                row
            )
            for row
            in conn.execute(
                select(
                    shared.observations
                )
            ).mappings().all()
        ]

    statuses = {
        row[
            "model_version"
        ]:
            row[
                "status"
            ]
        for row in stored
    }

    assert (
        statuses[
            "shadow-v2"
        ]
        == "settled"
    )

    assert (
        statuses[
            "shadow-v1"
        ]
        == "pending"
    )


def test_v2_settlement_wrapper_passes_current_model_version(
    monkeypatch,
):
    _patch_v2_model(
        monkeypatch
    )

    captured = {}

    def fake_settle(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "status":
                "SUCCESS",

            "checked":
                0,

            "settled":
                0,

            "pending":
                0,
        }

    monkeypatch.setattr(
        shared,
        "settle_pending_observations",
        fake_settle,
    )

    result = (
        v2obs
        .settle_pending_observations(
            limit=77,
            db_engine="db",
        )
    )

    assert (
        result[
            "status"
        ]
        == "SUCCESS"
    )

    assert (
        captured[
            "model_version"
        ]
        == "shadow-v2"
    )

    assert (
        captured[
            "limit"
        ]
        == 77
    )
