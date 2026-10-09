"""Historical training data cannot look ahead or mix competition identities."""
from leagues.chronological_training_data import (
    build_examples, chronological_split, labels,
)


def _row(day, home, away, hg, ag, *, slug="eng.1", key=None):
    return {
        "fixture_key": key or f"{day}:{slug}:{home}:{away}",
        "match_date": day, "league_slug": slug,
        "home_team": home, "away_team": away,
        "home_score": hg, "away_score": ag,
        "source": "openfootball/football.json",
        "source_sha256": "test",
    }


def test_same_day_matches_cannot_use_each_other_in_form_features():
    history = [
        _row("2026-01-01", "Team Alpha", "Team Beta", 1, 0),
        _row("2026-01-02", "Team Beta", "Team Alpha", 2, 0),
        _row("2026-01-03", "Team Alpha", "Team Beta", 1, 1),
        _row("2026-01-04", "Team Beta", "Team Alpha", 1, 0),
        # Two same-day rematches (artificial but tests leakage contract).
        _row("2026-01-05", "Team Alpha", "Team Beta", 5, 0),
        _row("2026-01-05", "Team Beta", "Team Alpha", 0, 5),
    ]
    report = build_examples(history, min_history=3)
    examples = [e for e in report["examples"]
                if e["match_date"] == "2026-01-05"]
    assert len(examples) == 2
    # Prior-day team A: 1 GF, 0 GA; 0 GF, 2 GA; 1 GF, 1 GA; 0 GF, 1 GA.
    # Same-day 5-0 scores cannot be seen in either match feature.
    assert all(e["home_history"]["matches"] == 4 for e in examples)
    assert all(e["home_history"]["goals_for"] < 2 for e in examples)
    assert report["feature_policy"] == "PRIOR_CALENDAR_DAY_ONLY"


def test_league_identity_isolation_with_same_named_teams():
    rows = [
        _row("2026-01-01", "United", "City", 1, 0, slug="eng.1"),
        _row("2026-01-02", "United", "City", 2, 1, slug="eng.1"),
        _row("2026-01-03", "United", "City", 1, 1, slug="eng.1"),
        _row("2026-01-04", "United", "City", 1, 0, slug="sco.1"),
    ]
    report = build_examples(rows, min_history=3)
    assert report["total_deduplicated_results"] == 4
    assert len(report["examples"]) == 0


def test_chronological_holdout_never_overlaps_training_dates():
    rows = []
    for n in range(1, 21):
        rows.append(_row(f"2026-01-{n:02d}", "Arsenal", "Chelsea",
                         n % 3, (n + 1) % 3))
    data = build_examples(rows, min_history=3)["examples"]
    split = chronological_split(data, train_fraction=.7)
    assert split["train"] and split["holdout"]
    assert max(x["match_date"] for x in split["train"]) < min(
        x["match_date"] for x in split["holdout"]
    )
    assert split["cutoff_date"] == min(x["match_date"] for x in split["holdout"])


def test_labels_cover_six_supported_match_outcomes():
    result = labels(2, 1)
    assert result == {
        "home_win": 1, "draw": 0, "away_win": 0,
        "over_1_5": 1, "over_2_5": 1, "btts_yes": 1,
    }
