import pandas as pd
import pytest

from leagues import football_first_challenger as challenger


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


def test_team_identity_separates_club_and_national_namespaces():
    assert (
        challenger.team_identity("Rangers", 39)
        != challenger.team_identity("Rangers", 1)
    )


def test_combine_results_prefers_explicit_history_provenance_on_overlap():
    legacy = pd.DataFrame([
        _row(
            "2025-01-01",
            "A",
            "B",
            2,
            1,
            league_id=2,
            league_name="UEFA Champions League",
        )
    ])
    history = pd.DataFrame([
        {
            "date": "2025-01-01",
            "home_team": "A",
            "away_team": "B",
            "home_score": 2,
            "away_score": 1,
            "league_id": 2,
            "competition": "UEFA Champions League",
        }
    ])

    combined, stats = challenger.combine_results(legacy, history)
    assert len(combined) == 1
    assert combined.iloc[0]["source_dataset"] == "football_history"
    assert stats["same_score_duplicates_removed"] == 1


def test_combine_results_fails_closed_on_conflicting_score():
    legacy = pd.DataFrame([
        _row(
            "2025-01-01",
            "A",
            "B",
            2,
            1,
            league_id=2,
            league_name="UEFA Champions League",
        )
    ])
    history = pd.DataFrame([
        {
            "date": "2025-01-01",
            "home_team": "A",
            "away_team": "B",
            "home_score": 1,
            "away_score": 1,
            "league_id": 2,
            "competition": "UEFA Champions League",
        }
    ])

    with pytest.raises(ValueError, match="Conflicting fixture result"):
        challenger.combine_results(legacy, history)


def test_feature_frame_contains_no_market_price_features():
    rows = []
    for index in range(1, 8):
        rows.append(
            _row(
                f"2025-01-{index:02d}",
                "A",
                "B",
                1 + (index % 2),
                index % 2,
            )
        )
        rows.append(
            _row(
                f"2025-01-{index:02d}",
                "C",
                "D",
                index % 2,
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
    features, stats = challenger.build_feature_frame(combined)

    assert stats["trainable_samples"] > 0
    assert not any(
        "odds" in column or column.startswith("mkt_")
        for column in challenger.FEATURE_COLUMNS
    )
    assert set(challenger.FEATURE_COLUMNS).issubset(features.columns)


def test_offline_evaluation_never_enables_promotion():
    rows = []
    for day in range(1, 46):
        date = (
            pd.Timestamp("2025-01-01")
            + pd.Timedelta(days=day)
        ).date().isoformat()
        rows.append(
            _row(
                date,
                "A",
                "B",
                day % 4,
                (day + 1) % 3,
            )
        )
        rows.append(
            _row(
                date,
                "C",
                "D",
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
    features, _ = challenger.build_feature_frame(combined)
    report = challenger.evaluate(features)

    assert report["promotion_enabled"] is False
    assert report["live_adjustment_allowed"] is False
    assert report["market_price_features_used"] == []
