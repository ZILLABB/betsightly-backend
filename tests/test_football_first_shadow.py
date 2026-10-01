
from datetime import datetime, timezone

import pytest

from leagues import football_first_shadow as shadow


class _Model:
    classes_ = [0, 1, 2]

    def predict_proba(self, X):
        return [[0.20, 0.25, 0.55]]


class _History:
    def __init__(self):
        rows = [
            {
                "venue": "home",
                "gf": 2,
                "ga": 1,
                "date": (
                    f"2026-09-{day:02d}"
                    "T12:00:00+00:00"
                ),
            }
            for day in range(1, 7)
        ]
        away_rows = [
            {
                "venue": "away",
                "gf": 1,
                "ga": 1,
                "date": (
                    f"2026-09-{day:02d}"
                    "T12:00:00+00:00"
                ),
            }
            for day in range(1, 7)
        ]

        self.by_team = {
            ("CLUB", "Home"): rows,
            ("CLUB", "Away"): away_rows,
        }

    def team_form(
        self,
        team,
        venue,
        team_type="CLUB",
    ):
        if team == "Home":
            return {
                "win_rate_5": .6,
                "win_rate_10": .5,
                "draw_rate_5": .2,
                "goals_scored_5": 1.6,
                "goals_conceded_5": .8,
                "venue_win_rate_5": .6,
                "venue_goals_5": 1.6,
            }
        return {
            "win_rate_5": .4,
            "win_rate_10": .4,
            "draw_rate_5": .4,
            "goals_scored_5": 1.0,
            "goals_conceded_5": 1.2,
            "venue_win_rate_5": .4,
            "venue_goals_5": 1.0,
        }

    def head_to_head(
        self,
        home,
        away,
        window=10,
        team_type="CLUB",
    ):
        return {
            "home_win_rate": .5,
            "avg_goals": 2.4,
            "btts_rate": .5,
            "meetings": 4,
        }


def _fixture(date="2026-10-01T15:00:00Z"):
    return {
        "commence_time": date,
        "team_type": "CLUB",
        "home": {
            "name": "Home",
        },
        "away": {
            "name": "Away",
        },
    }


def _state(monkeypatch):
    monkeypatch.setattr(
        shadow,
        "_load",
        lambda: {
            "loaded": True,
            "model": _Model(),
            "meta": {
                "model_version": "test-v1",
                "feature_version": (
                    "football-first-runtime-core-v1"
                ),
                "selected_family": "logistic",
                "training_cutoff": "2026-09-26",
                "trained_samples": 69952,
            },
        },
    )


def test_shadow_requires_future_fixture(monkeypatch):
    _state(monkeypatch)

    result = shadow.predict_fixture(
        _fixture(
            "2026-09-20T15:00:00Z"
        ),
        _History(),
        require_enabled=False,
    )

    assert (
        result["status"]
        == "TRAINING_OVERLAP"
    )


def test_shadow_returns_match_result_probabilities(monkeypatch):
    _state(monkeypatch)

    result = shadow.predict_fixture(
        _fixture(),
        _History(),
        require_enabled=False,
    )

    assert result["status"] == "READY"
    assert result["shadow_only"] is True
    assert result["publishable"] is False
    assert (
        result["probability_changed"]
        is False
    )
    assert (
        sum(
            result[
                "probabilities"
            ].values()
        )
        == pytest.approx(
            1.0,
            abs=1e-6,
        )
    )
    assert (
        result[
            "probabilities"
        ]["home_win"]
        == pytest.approx(.55)
    )


def test_shadow_market_probability_is_read_only(monkeypatch):
    _state(monkeypatch)

    result = shadow.predict_fixture(
        _fixture(),
        _History(),
        require_enabled=False,
    )

    assert (
        shadow.market_probability(
            result,
            "home_win",
        )
        == pytest.approx(.55)
    )
    assert (
        shadow.market_probability(
            result,
            "home_or_draw",
        )
        == pytest.approx(.80)
    )
    assert (
        shadow.market_probability(
            result,
            "over_1_5",
        )
        is None
    )


def test_disabled_shadow_does_not_load_artifact(monkeypatch):
    monkeypatch.delenv(
        shadow.FEATURE_FLAG,
        raising=False,
    )
    monkeypatch.setattr(
        shadow,
        "_load",
        lambda: pytest.fail(
            "disabled shadow must not load artifact"
        ),
    )

    result = shadow.predict_fixture(
        _fixture(),
        _History(),
    )

    assert result == {
        "status": "DISABLED",
        "shadow_only": True,
    }
