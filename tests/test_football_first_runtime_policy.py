
import pandas as pd

from leagues import (
    football_first_challenger as challenger,
)
from leagues import (
    football_first_runtime_policy as runtime_policy,
)


def _row(
    date,
    home,
    away,
    hs,
    aws,
    league_id=39,
    league_name="League",
):
    return {
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": hs,
        "away_score": aws,
        "league_id": league_id,
        "league_name": league_name,
    }


def _features():
    rows = []
    start = pd.Timestamp(
        "2023-01-01"
    )

    for day in range(260):
        date = (
            start
            + pd.Timedelta(
                days=day
            )
        ).date().isoformat()

        rows.extend([
            _row(
                date,
                "A",
                "B",
                (day + 1) % 4,
                day % 2,
                39,
                "League One",
            ),
            _row(
                date,
                "C",
                "D",
                (day + 2) % 3,
                (day + 1) % 2,
                39,
                "League One",
            ),
            _row(
                date,
                "E",
                "F",
                day % 3,
                (day + 2) % 3,
                40,
                "League Two",
            ),
            _row(
                date,
                "G",
                "H",
                (day + 1) % 3,
                day % 2,
                40,
                "League Two",
            ),
        ])

    combined, _ = (
        challenger.combine_results(
            pd.DataFrame(
                rows
            ),
            pd.DataFrame(
                columns=[
                    "date",
                    "home_team",
                    "away_team",
                    "home_score",
                    "away_score",
                    "league_id",
                    "competition",
                ]
            ),
        )
    )
    features, _ = (
        challenger.build_feature_frame(
            combined
        )
    )
    return features


def test_runtime_policy_never_grants_live_credit():
    report = (
        runtime_policy
        .derive_runtime_league_target_evidence(
            _features(),
            n_folds=3,
        )
    )

    assert (
        report[
            "automatic_promotion"
        ]
        is False
    )
    assert (
        report[
            "live_adjustment_allowed"
        ]
        is False
    )
    assert (
        report[
            "counts_as_prospective_model_policy_evidence"
        ]
        is False
    )

    for target in report[
        "targets"
    ].values():
        for row in target[
            "league_evidence"
        ]:
            assert (
                row["offline_only"]
                is True
            )
            assert (
                row[
                    "production_promotion_credit"
                ]
                is False
            )


def test_runtime_policy_uses_runtime_core_version():
    report = (
        runtime_policy
        .derive_runtime_league_target_evidence(
            _features(),
            n_folds=3,
        )
    )

    assert (
        report[
            "runtime_feature_version"
        ]
        == "football-first-runtime-core-v1"
    )
    assert (
        "elo_home_expectation"
        not in report[
            "runtime_feature_columns"
        ]
    )
    assert (
        "competition_over_1_5_rate"
        not in report[
            "runtime_feature_columns"
        ]
    )
