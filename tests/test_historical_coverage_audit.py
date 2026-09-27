import pandas as pd

from scripts.audit_historical_coverage import candidate_divisions


def test_keyword_candidate_beats_unrelated_division():
    frame = pd.DataFrame({
        "Division": [
            "UEFA Champions League",
            "English Premier League",
        ],
        "MatchDate": ["2025-01-01", "2025-01-02"],
        "OddHome": [2.0, 2.0],
        "OddDraw": [3.0, 3.0],
        "OddAway": [4.0, 4.0],
        "Over25": [1.9, 1.9],
        "Under25": [1.9, 1.9],
    })

    out = candidate_divisions(
        frame,
        {
            "name": "UEFA Champions League",
            "aliases": ["champions league", "uefa champions league"],
        },
    )

    assert out
    assert out[0]["division"] == "UEFA Champions League"
    assert out[0]["keyword_match"] is True


def test_candidate_reports_odds_coverage():
    frame = pd.DataFrame({
        "Division": ["K League 1", "K League 1"],
        "MatchDate": ["2025-01-01", "2025-01-02"],
        "OddHome": [2.0, None],
        "OddDraw": [3.0, None],
        "OddAway": [4.0, None],
        "Over25": [1.9, None],
        "Under25": [1.9, None],
    })

    out = candidate_divisions(
        frame,
        {"name": "K League 1", "aliases": ["k league 1", "k league"]},
    )

    assert out[0]["rows"] == 2
    assert out[0]["complete_1x2_pct"] == 50.0
    assert out[0]["complete_ou25_pct"] == 50.0
