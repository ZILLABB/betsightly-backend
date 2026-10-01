import pandas as pd
import pytest

from leagues import elo_core
from leagues.football_first_runtime_elo import (
    attach_historical_runtime_elo,
    runtime_elo_feature_vector,
)


def _combined():
    rows = []
    for day, hs, aws in [
        ("2025-01-01", 2, 0),
        ("2025-01-10", 1, 0),
        ("2025-01-20", 0, 1),
        ("2025-02-01", 3, 1),
    ]:
        rows.append({
            "date": day,
            "league_id": 39,
            "competition": "Premier League",
            "home_team": "A",
            "away_team": "B",
            "home_score": hs,
            "away_score": aws,
            "source_dataset": "test",
            "source_class": "RESULTS_ONLY",
            "team_type": "CLUB",
        })
    return pd.DataFrame(rows)


def test_offline_and_runtime_elo_vectors_match_for_same_history():
    combined = _combined()
    target = pd.DataFrame([{
        "date": "2025-02-10",
        "league_id": 39,
        "competition": "Premier League",
        "home_team": "A",
        "away_team": "B",
    }])
    offline, stats = attach_historical_runtime_elo(combined, target)
    row = offline.iloc[0]

    matches = [
        {
            "home": "A",
            "away": "B",
            "hs": int(item["home_score"]),
            "as": int(item["away_score"]),
            "neutral": False,
        }
        for item in combined.to_dict("records")
    ]
    ratings, counts = elo_core.run_elo(matches)
    runtime = runtime_elo_feature_vector(
        {
            "league_slug": "eng.1",
            "neutral_venue": False,
            "home": {"name": "A"},
            "away": {"name": "B"},
        },
        {
            "eng.1": {
                "A": {"rating": ratings["A"], "matches": counts["A"]},
                "B": {"rating": ratings["B"], "matches": counts["B"]},
            }
        },
    )
    assert stats["available"] == 1
    assert runtime["status"] == "READY"
    for column, value in runtime["features"].items():
        assert float(row[column]) == pytest.approx(float(value), abs=1e-12)


def test_historical_elo_excludes_same_day_results():
    combined = _combined()
    combined = pd.concat([
        combined,
        pd.DataFrame([{
            "date": "2025-02-10",
            "league_id": 39,
            "competition": "Premier League",
            "home_team": "A",
            "away_team": "B",
            "home_score": 9,
            "away_score": 0,
            "source_dataset": "test",
            "source_class": "RESULTS_ONLY",
            "team_type": "CLUB",
        }]),
    ], ignore_index=True)
    target = pd.DataFrame([{
        "date": "2025-02-10",
        "league_id": 39,
        "competition": "Premier League",
        "home_team": "A",
        "away_team": "B",
    }])

    with_same_day, _ = attach_historical_runtime_elo(combined, target)
    without_same_day, _ = attach_historical_runtime_elo(
        combined[combined["date"] != "2025-02-10"],
        target,
    )
    assert (
        with_same_day.iloc[0]["runtime_elo_home_expectation"]
        == pytest.approx(
            without_same_day.iloc[0]["runtime_elo_home_expectation"],
            abs=1e-12,
        )
    )


def test_tournament_context_fails_closed_for_phase8_elo():
    result = runtime_elo_feature_vector(
        {
            "league_slug": "uefa.champions",
            "home": {"name": "A"},
            "away": {"name": "B"},
        },
        {},
    )
    assert result["status"] == "UNSUPPORTED_CONTEXT"
    assert result["features"]["runtime_elo_available"] == 0.0



def test_runtime_elo_uses_verified_alias_identity():
    result = runtime_elo_feature_vector(
        {
            "league_slug": "eng.1",
            "neutral_venue": False,
            "home": {"name": "Man United"},
            "away": {"name": "Liverpool"},
        },
        {
            "eng.1": {
                "Manchester United": {
                    "rating": 1600.0,
                    "matches": 10,
                },
                "Liverpool": {
                    "rating": 1580.0,
                    "matches": 10,
                },
            }
        },
    )

    assert result["status"] == "READY"
    assert (
        result["features"]["runtime_elo_available"]
        == 1.0
    )


def test_runtime_elo_fails_closed_outside_identity_allowlist():
    result = runtime_elo_feature_vector(
        {
            "league_slug": "fin.1",
            "neutral_venue": False,
            "home": {"name": "HJK"},
            "away": {"name": "KuPS"},
        },
        {
            "fin.1": {
                "HJK": {
                    "rating": 1600.0,
                    "matches": 10,
                },
                "KuPS": {
                    "rating": 1580.0,
                    "matches": 10,
                },
            }
        },
    )

    assert result["status"] == "UNSUPPORTED_CONTEXT"
    assert (
        result["features"]["runtime_elo_available"]
        == 0.0
    )
