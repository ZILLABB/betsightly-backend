import pandas as pd
import pytest

from leagues import (
    football_first_shadow_v2
    as shadow,
)


class _Model:
    classes_ = [
        0,
        1,
        2,
    ]

    def __init__(self):
        self.last_shape = None

    def predict_proba(
        self,
        X,
    ):
        self.last_shape = X.shape
        return [[
            0.20,
            0.25,
            0.55,
        ]]


class _History:
    def __init__(self):

        self.by_team = {
            (
                "CLUB",
                "Home",
            ): [
                {
                    "venue":
                        "home",
                    "gf":
                        2,
                    "ga":
                        1,
                    "date":
                        f"2026-09-{day:02d}T12:00:00",
                }
                for day
                in range(
                    1,
                    7,
                )
            ],

            (
                "CLUB",
                "Away",
            ): [
                {
                    "venue":
                        "away",
                    "gf":
                        1,
                    "ga":
                        1,
                    "date":
                        f"2026-09-{day:02d}T12:00:00",
                }
                for day
                in range(
                    1,
                    7,
                )
            ],
        }

    def team_form(
        self,
        team,
        venue,
        team_type="CLUB",
    ):
        if team == "Home":
            return {
                "win_rate_5":
                    .6,
                "win_rate_10":
                    .5,
                "draw_rate_5":
                    .2,
                "goals_scored_5":
                    1.6,
                "goals_conceded_5":
                    .8,
                "venue_win_rate_5":
                    .6,
                "venue_goals_5":
                    1.6,
            }

        return {
            "win_rate_5":
                .4,
            "win_rate_10":
                .4,
            "draw_rate_5":
                .4,
            "goals_scored_5":
                1.0,
            "goals_conceded_5":
                1.2,
            "venue_win_rate_5":
                .4,
            "venue_goals_5":
                1.0,
        }

    def head_to_head(
        self,
        home,
        away,
        window=10,
        team_type="CLUB",
    ):
        return {
            "home_win_rate":
                .5,
            "avg_goals":
                2.4,
            "btts_rate":
                .5,
            "meetings":
                4,
        }


def _fixture(
    slug="eng.1",
):
    return {
        "event_id":
            "phase9-test-1",
        "commence_time":
            "2026-10-01T15:00:00Z",
        "league_slug":
            slug,
        "league":
            "Test League",
        "team_type":
            "CLUB",
        "home": {
            "name":
                "Home",
        },
        "away": {
            "name":
                "Away",
        },
    }


def _cached_rates():
    return {
        "eng.1": {
            "matches":
                30,
            "avg_goals":
                2.6,
            "over_1_5":
                .72,
            "over_2_5":
                .53,
            "home_win":
                .46,
            "draw":
                .25,
            "away_win":
                .29,
            "btts":
                .51,
            "home_goals":
                1.45,
            "away_goals":
                1.15,
        },
        "_priors": {},
    }


def _ratings():
    return {
        "eng.1": {
            "Home": {
                "rating":
                    1600.0,
                "matches":
                    10,
            },
            "Away": {
                "rating":
                    1550.0,
                "matches":
                    10,
            },
        }
    }


def _state(
    monkeypatch,
):
    model = _Model()

    monkeypatch.setattr(
        shadow,
        "_load",
        lambda: {
            "loaded":
                True,
            "model":
                model,
            "meta": {
                "model_version":
                    "v2-test",
                "feature_version":
                    "football-first-runtime-v2-candidate-32-v1",
                "feature_count":
                    32,
                "selected_family":
                    "logistic",
                "training_cutoff":
                    "2026-06-01",
                "trained_samples":
                    71748,
                "eligible_league_ids": [
                    39,
                ],
            },
            "error":
                None,
        },
    )

    return model


def test_v2_runtime_vector_is_exactly_32(
    monkeypatch,
):
    model = _state(
        monkeypatch
    )

    result = shadow.predict_fixture(
        _fixture(),
        _History(),
        _cached_rates(),
        _ratings(),
        require_enabled=False,
    )

    assert (
        result["status"]
        == "READY"
    )

    assert (
        result[
            "feature_count"
        ]
        == 32
    )

    assert (
        model.last_shape
        == (
            1,
            32,
        )
    )

    assert (
        result[
            "probability_changed"
        ]
        is False
    )

    assert (
        result[
            "selection_changed"
        ]
        is False
    )

    assert sum(
        result[
            "probabilities"
        ].values()
    ) == pytest.approx(
        1.0,
        abs=1e-6,
    )


def test_v2_runtime_fails_closed_outside_allowlist(
    monkeypatch,
):
    _state(
        monkeypatch
    )

    result = shadow.predict_fixture(
        _fixture(
            "ger.2"
        ),
        _History(),
        _cached_rates(),
        {},
        require_enabled=False,
    )

    assert (
        result[
            "status"
        ]
        == "UNSUPPORTED_LEAGUE"
    )
