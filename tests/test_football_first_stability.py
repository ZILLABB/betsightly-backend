import pandas as pd

from leagues import football_first_challenger as challenger
from leagues import football_first_stability as stability


def _row(date, home, away, hs, aws):
    return {
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": hs,
        "away_score": aws,
        "league_id": 39,
        "league_name": "Premier League",
    }


def _features():
    rows = []
    start = pd.Timestamp("2024-01-01")
    teams = ["A", "B", "C", "D", "E", "F"]
    for day in range(180):
        date = (start + pd.Timedelta(days=day)).date().isoformat()
        home1 = teams[day % 6]
        away1 = teams[(day + 1) % 6]
        home2 = teams[(day + 2) % 6]
        away2 = teams[(day + 3) % 6]
        rows.append(
            _row(
                date,
                home1,
                away1,
                (day + 1) % 4,
                day % 3,
            )
        )
        rows.append(
            _row(
                date,
                home2,
                away2,
                (day + 2) % 3,
                (day + 1) % 2,
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
    features, _ = challenger.build_feature_frame(combined)
    return features


def test_temporal_folds_never_overlap_future_into_training():
    features = _features()
    folds = stability.temporal_folds(
        features,
        n_folds=3,
    )

    assert len(folds) == 3
    for fold in folds:
        assert fold["train_end"] < fold["calib_start"]
        assert fold["calib_end"] < fold["test_start"]


def test_walk_forward_remains_offline_only():
    report = stability.evaluate_walk_forward(
        _features(),
        n_folds=2,
    )

    assert report["promotion_enabled"] is False
    assert report["live_adjustment_allowed"] is False
    assert report["promotion_state"] == "OFFLINE_ONLY"
    assert report["targets"]["match_result"]["fold_count"] == 2
