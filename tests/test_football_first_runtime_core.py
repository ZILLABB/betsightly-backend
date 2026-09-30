
import pandas as pd
import pytest

from leagues import football_first_challenger as challenger
from leagues import football_first_runtime_core as runtime_core
from leagues.team_history import HistoryIndex


def _row(
    date,
    home,
    away,
    hs,
    aws,
    league_id=39,
    league_name="Premier League",
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


def test_runtime_core_has_no_known_drifting_features():
    excluded = {
        "competition_home_goals",
        "competition_away_goals",
        "competition_over_1_5_rate",
        "competition_over_2_5_rate",
        "competition_btts_rate",
        "elo_home_expectation",
        "elo_diff_scaled",
        "home_rest_days_scaled",
        "away_rest_days_scaled",
        "home_home_win_rate_5",
        "home_home_goals_5",
        "away_away_win_rate_5",
        "away_away_goals_5",
    }
    assert excluded.isdisjoint(
        runtime_core.RUNTIME_FEATURE_COLUMNS
    )


def test_no_h2h_defaults_are_normalized_to_runtime_contract():
    frame = pd.DataFrame([
        {
            **{
                column: 0.5
                for column in runtime_core.RUNTIME_FEATURE_COLUMNS
            },
            "h2h_meetings": 0.0,
        }
    ])
    normalized = (
        runtime_core.normalize_runtime_core_frame(
            frame
        )
    )
    row = normalized.iloc[0]

    assert row["h2h_home_win_rate"] == pytest.approx(.40)
    assert row["h2h_avg_goals"] == pytest.approx(2.70)
    assert row["h2h_btts_rate"] == pytest.approx(.52)
    assert row["h2h_meetings"] == pytest.approx(0.0)


def test_runtime_vector_fails_closed_below_five_matches():
    index = HistoryIndex({
        "matches": [
            {
                "date": "2025-01-01T12:00:00+00:00",
                "home": "A",
                "away": "B",
                "hs": 1,
                "as": 0,
                "team_type": "CLUB",
            }
        ]
    })
    result = runtime_core.runtime_feature_vector(
        {
            "team_type": "CLUB",
            "home": {"name": "A"},
            "away": {"name": "B"},
        },
        index,
    )
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["vector"] is None


def test_offline_target_row_matches_runtime_history_index_vector():
    rows = []
    history_matches = []

    # Ten prior meetings give both sides enough team form and H2H history.
    for day in range(1, 11):
        date = f"2025-01-{day:02d}"
        hs = 2 if day % 2 else 1
        aws = 0 if day % 3 else 1
        rows.append(
            _row(
                date,
                "A",
                "B",
                hs,
                aws,
            )
        )
        history_matches.append({
            "date": date + "T12:00:00+00:00",
            "home": "A",
            "away": "B",
            "hs": hs,
            "as": aws,
            "team_type": "CLUB",
        })

    # The target result is present only so the offline builder can create its
    # pre-match row.  It must not be in the runtime HistoryIndex.
    rows.append(
        _row(
            "2025-01-20",
            "A",
            "B",
            1,
            1,
        )
    )

    combined, _ = challenger.combine_results(
        pd.DataFrame(rows),
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
    features, _ = challenger.build_feature_frame(
        combined
    )
    normalized = runtime_core.normalize_runtime_core_frame(
        features
    )
    offline = normalized[
        normalized["date"] == "2025-01-20"
    ].iloc[0]

    index = HistoryIndex({
        "matches": history_matches
    })
    runtime = runtime_core.runtime_feature_vector(
        {
            "team_type": "CLUB",
            "home": {"name": "A"},
            "away": {"name": "B"},
        },
        index,
    )

    assert runtime["status"] == "READY"

    for column in runtime_core.RUNTIME_FEATURE_COLUMNS:
        assert runtime["features"][column] == pytest.approx(
            float(offline[column]),
            abs=1e-12,
        )


def test_runtime_core_evaluation_never_starts_promotion():
    rows = []
    start = pd.Timestamp("2024-01-01")
    teams = ["A", "B", "C", "D", "E", "F"]

    for day in range(180):
        date = (
            start + pd.Timedelta(days=day)
        ).date().isoformat()
        rows.append(
            _row(
                date,
                teams[day % 6],
                teams[(day + 1) % 6],
                (day + 1) % 4,
                day % 3,
            )
        )
        rows.append(
            _row(
                date,
                teams[(day + 2) % 6],
                teams[(day + 3) % 6],
                (day + 2) % 3,
                day % 2,
            )
        )

    combined, _ = challenger.combine_results(
        pd.DataFrame(rows),
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
    features, _ = challenger.build_feature_frame(
        combined
    )
    report = (
        runtime_core.evaluate_runtime_core_walk_forward(
            features,
            n_folds=2,
        )
    )

    assert report["automatic_promotion"] is False
    assert report["live_adjustment_allowed"] is False
    assert report["prospective_observation_started"] is False
