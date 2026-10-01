import pandas as pd
from leagues.football_first_coverage import historical_coverage_report


def test_coverage_report_exposes_missing_target_leagues():
    combined = pd.DataFrame([
        {
            "date": "2025-01-01",
            "league_id": 39,
            "competition": "Premier League",
            "source_dataset": "legacy_training_baseline",
        },
        {
            "date": "2025-01-02",
            "league_id": 39,
            "competition": "Premier League",
            "source_dataset": "football_history",
        },
    ])
    features = pd.DataFrame([{"date": "2025-01-02", "league_id": 39}])
    report = historical_coverage_report(
        combined,
        features,
        target_league_ids={39, 307},
    )
    assert report["target_leagues_present"] == [39]
    assert report["target_leagues_missing"] == [307]
    assert report["overview"]["unique_results"] == 2
    assert report["overview"]["trainable_samples"] == 1
