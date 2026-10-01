from leagues import (
    football_first_shadow_v2_automation
    as automation,
)


def test_v2_automation_is_staging_only(
    monkeypatch,
):
    monkeypatch.setenv(
        "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_ENABLED",
        "true",
    )

    monkeypatch.setenv(
        "ENVIRONMENT",
        "production",
    )

    assert (
        automation.enabled()
        is False
    )

    monkeypatch.setenv(
        "ENVIRONMENT",
        "development",
    )

    assert (
        automation.enabled()
        is False
    )

    monkeypatch.setenv(
        "ENVIRONMENT",
        "staging",
    )

    assert (
        automation.enabled()
        is True
    )


def test_v2_automation_requires_explicit_flag(
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "staging",
    )

    monkeypatch.delenv(
        "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_ENABLED",
        raising=False,
    )

    assert (
        automation.enabled()
        is False
    )


def test_v2_automation_run_once_collects_fresh_board(
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "staging",
    )

    monkeypatch.setenv(
        "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_ENABLED",
        "true",
    )

    from leagues import engine

    calls = []
    order = []

    monkeypatch.setattr(
        automation,
        "_refresh_staging_history",
        lambda: (
            order.append("history")
            or {
                "status": "READY",
                "usable": True,
                "staging_only": True,
                "base_rates_built_at":
                    "2026-10-01T09:00:00+00:00",
                "team_history_built_at":
                    "2026-10-01T09:00:01+00:00",
                "base_rate_competition_count":
                    64,
                "team_history_match_count":
                    999,
                "readiness_state":
                    "READY",
            }
        ),
    )

    monkeypatch.setattr(
        engine,
        "run_pipeline",
        lambda days_ahead, force: (
            order.append("pipeline")
            or calls.append(
                (
                    days_ahead,
                    force,
                )
            )
            or (
                [
                    {
                        "pick":
                            1,
                    },
                    {
                        "pick":
                            2,
                    },
                ],
                [
                    {
                        "fixture":
                            1,
                    },
                    {
                        "fixture":
                            2,
                    },
                    {
                        "fixture":
                            3,
                    },
                ],
            )
        ),
    )

    from leagues import (
        football_first_shadow_v2_observations
        as v2obs,
    )
    from leagues import builder_v2

    monkeypatch.setattr(
        builder_v2,
        "list_candidates",
        lambda options: {
            "status": "success",
            "candidate_count": 506,
            "selection_diagnostics": {
                "staging_supplemental_counts": {
                    "qualified_pool": 14,
                    "prepared_bookable": 14,
                    "after_trust_and_policy": 14,
                    "approved": 14,
                },
                "staging_supplemental_bookability_rejections": {},
            },
            "board": {"board_snapshot_id": "snapshot-test"},
        },
    )

    monkeypatch.setattr(
        v2obs,
        "shadow_report",
        lambda: {
            "observations": {
                "total":
                    42,

                "pending":
                    35,

                "settled":
                    7,
            }
        },
    )

    result = (
        automation.run_once()
    )

    assert (
        result[
            "status"
        ]
        == "SUCCESS"
    )

    assert calls == [
        (
            7,
            True,
        )
    ]

    assert order == [
        "history",
        "pipeline",
    ]

    assert (
        result[
            "history"
        ][
            "status"
        ]
        == "READY"
    )

    assert (
        result[
            "fixtures"
        ]
        == 3
    )

    assert (
        result[
            "picks"
        ]
        == 2
    )

    assert (
        result[
            "v2_observations"
        ][
            "total"
        ]
        == 42
    )

    assert result["builder"]["candidate_count"] == 506
    assert result["builder"]["supplemental_qualified"] == 14
    assert result["builder"]["supplemental_bookable"] == 14
    assert result["builder"]["supplemental_approved"] == 14

    state = (
        automation.status()
    )

    assert (
        state[
            "last_v2_total"
        ]
        == 42
    )

    assert (
        state[
            "last_v2_pending"
        ]
        == 35
    )

    assert (
        state[
            "last_v2_settled"
        ]
        == 7
    )

    assert state["last_builder_candidate_count"] == 506
    assert state["last_supplemental_qualified"] == 14
    assert state["last_supplemental_bookable"] == 14
    assert state["last_supplemental_approved"] == 14

    assert (
        state[
            "production_allowed"
        ]
        is False
    )

    assert (
        state[
            "automatic_promotion"
        ]
        is False
    )


def test_v2_automation_does_not_run_pipeline_without_usable_history(
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "staging",
    )

    monkeypatch.setenv(
        "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_ENABLED",
        "true",
    )

    monkeypatch.setattr(
        automation,
        "_refresh_staging_history",
        lambda: {
            "status": "NOT_READY",
            "usable": False,
            "staging_only": True,
            "base_rates_built_at": None,
            "team_history_built_at": None,
            "base_rate_competition_count": 0,
            "team_history_match_count": 0,
            "readiness_state": "ABSENT",
        },
    )

    from leagues import engine

    pipeline_calls = []

    monkeypatch.setattr(
        engine,
        "run_pipeline",
        lambda *args, **kwargs: (
            pipeline_calls.append(
                (
                    args,
                    kwargs,
                )
            )
        ),
    )

    result = automation.run_once()

    assert result["status"] == "ERROR"
    assert result["error_type"] == "RuntimeError"
    assert pipeline_calls == []

    state = automation.status()

    assert (
        state["last_history_refresh_status"]
        == "NOT_READY"
    )

    assert state["production_allowed"] is False
    assert state["automatic_promotion"] is False


def test_v2_automation_run_once_fails_closed_when_disabled(
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "production",
    )

    monkeypatch.setenv(
        "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_ENABLED",
        "true",
    )

    result = (
        automation.run_once()
    )

    assert (
        result[
            "status"
        ]
        == "DISABLED"
    )
