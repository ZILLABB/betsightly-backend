import pandas as pd

from scripts.audit_training_data import (
    duplicate_summary,
    eligible_training_dates,
    team_country_collisions,
)


def _row(day, home, away, hs=1, aws=0, country="X"):
    return {
        "date": pd.Timestamp(day, tz="UTC"),
        "home_team": home,
        "away_team": away,
        "home_score": hs,
        "away_score": aws,
        "country": country,
    }


def test_warmup_uses_strictly_earlier_dates():
    rows = []
    # A and B play five prior dates.
    for day in range(1, 6):
        rows.append(_row(f"2026-01-0{day}", "A", "B"))
    # Two fixtures on day six should both be eligible; neither same-day row
    # may be used to make the other eligible.
    rows.append(_row("2026-01-06", "A", "B"))
    rows.append(_row("2026-01-06", "A", "B"))
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    dates = eligible_training_dates(df)

    assert len(dates) == 2
    assert {d.date().isoformat() for d in dates} == {"2026-01-06"}


def test_duplicate_summary_detects_conflicting_scores():
    df = pd.DataFrame([
        _row("2026-01-01", "Alpha FC", "Beta", 1, 0),
        _row("2026-01-01", "alpha fc", "Beta", 2, 0),
    ])

    summary = duplicate_summary(df)

    assert summary["duplicate_keys"] == 1
    assert summary["conflicting_score_keys"] == 1


def test_team_country_collision_is_visible():
    df = pd.DataFrame([
        _row("2026-01-01", "Rangers", "One", country="Scotland"),
        _row("2026-01-02", "Rangers", "Two", country="Nigeria"),
    ])

    collisions = team_country_collisions(df)

    assert collisions
    assert collisions[0]["normalized_team"] == "rangers"
    assert set(collisions[0]["countries"]) == {"Scotland", "Nigeria"}
