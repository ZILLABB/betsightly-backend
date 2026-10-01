from copy import deepcopy
from datetime import date, timedelta

from leagues.context_challenger import (
    evaluate_context_challenger,
)


def _dataset(
    *,
    holdout_reversal=False,
):
    start = date(
        2026,
        1,
        1,
    )

    rows = []

    # Ten whole match dates.
    # 12 exposed + 12 control observations per day.
    # 70% time split => 84/group training, 36/group holdout.
    for day_index in range(10):
        match_date = (
            start
            + timedelta(
                days=day_index,
            )
        ).isoformat()

        is_holdout = (
            day_index >= 7
        )

        # short_rest exposed:
        # training lands 6/12 (50%) against 75% predicted.
        # normal-rest control lands 9/12 (75%).
        #
        # Normal case: holdout repeats the differential.
        # Reversal case: holdout exposed lands 9/12 and therefore does not
        # justify the training adjustment.
        exposed_wins = (
            9
            if (
                holdout_reversal
                and is_holdout
            )
            else 6
        )

        for index in range(12):
            rows.append({
                "date": match_date,
                "market": "over_1_5",
                "probability": .75,
                "outcome": (
                    1.0
                    if index < exposed_wins
                    else 0.0
                ),
                "labels": {
                    "rest": "short_rest",
                    "lineups": "unknown",
                    "injuries": "unknown",
                    "suspensions": "unknown",
                    "congestion": "unknown",
                    "weather": "unknown",
                },
            })

        for index in range(12):
            rows.append({
                "date": match_date,
                "market": "over_1_5",
                "probability": .75,
                "outcome": (
                    1.0
                    if index < 9
                    else 0.0
                ),
                "labels": {
                    "rest": "normal_rest",
                    "lineups": "unknown",
                    "injuries": "unknown",
                    "suspensions": "unknown",
                    "congestion": "unknown",
                    "weather": "unknown",
                },
            })

    return rows


def _rest_evaluation(report):
    return next(
        row
        for row in report["evaluations"]
        if (
            row["market"]
            == "over_1_5"
            and row["dimension"]
            == "rest"
        )
    )


def test_offline_challenger_uses_earlier_training_and_later_holdout():
    rows = _dataset()

    original = deepcopy(
        rows
    )

    report = evaluate_context_challenger(
        rows
    )

    rest = _rest_evaluation(
        report
    )

    assert report["holdout_start_date"] == "2026-01-08"

    assert rest["train_exposed_n"] == 84
    assert rest["train_control_n"] == 84

    assert rest["holdout_exposed_n"] == 36
    assert rest["holdout_control_n"] == 36

    assert rest["status"] == "shadow_candidate"
    assert rest["shadow_candidate"] is True

    assert (
        rest["training_adjustment"]
        < 0
    )

    assert (
        rest["holdout"]["challenger_brier"]
        < rest["holdout"]["baseline_brier"]
    )

    assert report["promotion_enabled"] is False
    assert report["live_adjustment_allowed"] is False
    assert report["selection_changed"] is False

    # Evaluation is isolated and cannot mutate archived baseline facts.
    assert rows == original


def test_offline_challenger_rejects_training_signal_that_fails_later():
    report = evaluate_context_challenger(
        _dataset(
            holdout_reversal=True,
        )
    )

    rest = _rest_evaluation(
        report
    )

    assert (
        rest["status"]
        == "rejected_holdout"
    )

    assert rest["shadow_candidate"] is False
    assert rest["promotion_enabled"] is False
    assert rest["live_adjustment_allowed"] is False


def test_offline_challenger_refuses_small_samples():
    rows = []

    for index in range(20):
        rows.append({
            "date": (
                "2026-01-01"
                if index < 10
                else "2026-01-02"
            ),
            "market": "over_1_5",
            "probability": .75,
            "outcome": float(
                index % 2 == 0
            ),
            "labels": {
                "rest": (
                    "short_rest"
                    if index % 2
                    else "normal_rest"
                ),
            },
        })

    report = evaluate_context_challenger(
        rows
    )

    rest = _rest_evaluation(
        report
    )

    assert (
        rest["status"]
        == "insufficient_training_sample"
    )

    assert rest["shadow_candidate"] is False
