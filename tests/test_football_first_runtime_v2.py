from collections import deque

import pandas as pd
import pytest

from leagues.base_rates import (
    _empty,
    rates_for,
)

from leagues.football_first_runtime_v2 import (
    _base_values,
    _cached_rates,
    _sample_delta,
    _venue_values,
    rest_snapshot,
)


def test_base_replay_uses_live_rates_for_math():

    sample = _empty()

    for hs, aws in [
        (2, 0),
        (1, 1),
        (0, 1),
        (3, 1),
    ]:
        _sample_delta(
            sample,
            hs,
            aws,
            1,
        )

    cached = _cached_rates({
        "eng.1":
            sample
    })

    direct = rates_for(
        "eng.1",
        cached,
    )

    features = _base_values(
        "eng.1",
        cached,
    )

    assert (
        features[
            "runtime_base_home_win"
        ]
        == pytest.approx(
            direct[
                "home_win"
            ]
        )
    )

    assert (
        features[
            "runtime_base_draw"
        ]
        == pytest.approx(
            direct[
                "draw"
            ]
        )
    )

    assert (
        features[
            "runtime_base_over_2_5"
        ]
        == pytest.approx(
            direct[
                "over_2_5"
            ]
        )
    )

    assert (
        features[
            "runtime_base_btts"
        ]
        == pytest.approx(
            direct[
                "btts"
            ]
        )
    )


def test_venue_values_match_history_index_semantics():

    rows = deque([
        {
            "venue": "home",
            "gf": 1,
            "ga": 0,
        },
        {
            "venue": "away",
            "gf": 0,
            "ga": 2,
        },
        {
            "venue": "home",
            "gf": 2,
            "ga": 2,
        },
        {
            "venue": "home",
            "gf": 3,
            "ga": 1,
        },
    ])

    win, goals = _venue_values(
        rows,
        "home",
    )

    assert win == pytest.approx(
        2 / 3
    )

    assert goals == pytest.approx(
        2.0
    )


def test_venue_default_matches_runtime_neutral():

    win, goals = _venue_values(
        deque(),
        "home",
    )

    assert win == pytest.approx(
        0.40
    )

    assert goals == pytest.approx(
        1.35
    )


def test_rest_shared_calendar_contract():

    result = rest_snapshot(
        pd.Timestamp(
            "2026-05-10"
        ),
        [
            pd.Timestamp(
                "2026-05-07"
            )
        ],
    )

    assert (
        result[
            "available"
        ]
        == 1.0
    )

    assert (
        result[
            "days_scaled"
        ]
        == pytest.approx(
            3 / 30
        )
    )

    assert (
        result[
            "short_rest"
        ]
        == 1.0
    )


def test_rest_default_is_neutral_when_unseen():

    result = rest_snapshot(
        pd.Timestamp(
            "2026-05-10"
        ),
        [],
    )

    assert (
        result[
            "available"
        ]
        == 0.0
    )

    assert (
        result[
            "days_scaled"
        ]
        == pytest.approx(
            7 / 30
        )
    )

    assert (
        result[
            "short_rest"
        ]
        == 0.0
    )
