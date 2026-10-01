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

    monkeypatch.setattr(
        engine,
        "run_pipeline",
        lambda days_ahead, force: (
            calls.append(
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
