"""Current bookmaker inventory joins only earlier same-league results."""
from datetime import datetime, timedelta, timezone

from leagues.staging_source_history_coverage import compare_coverage


def _entry(event_id, home="Arsenal", away="Chelsea", *,
           competition="Premier League", tid="sr:tournament:17",
           cid="sr:category:1"):
    return {
        "event_id": event_id, "home_team": home, "away_team": away,
        "competition": competition, "sportybet_tournament_id": tid,
        "sportybet_category_id": cid,
        "kickoff_ms": int(datetime(
            2026, 10, 9, 12, tzinfo=timezone.utc,
        ).timestamp() * 1000),
        "prices": {"over_1_5": 1.48},
        "home_squad": "", "away_squad": "",
    }


def _rows(slug="eng.1", *, teams=("Arsenal", "Chelsea")):
    return [
        {
            "league_slug": slug, "fixture_key": f"{slug}:{i}",
            "match_date": (datetime(2026, 9, 1) + timedelta(days=i)).date(),
            "home_team": teams[i % 2], "away_team": teams[(i + 1) % 2],
        }
        for i in range(12)
    ]


def test_verified_prior_matches_enable_potential_shadow_histories():
    report = compare_coverage(
        {"one": [_entry("123")]},
        _rows(),
        "2026-10-09",
    )
    assert report["potential_shadow_ready_count"] == 1
    assert report["shadow_ready_examples"][0]["competition_history"] == 12
    assert report["champion_model_unchanged"] is True
    assert report["publishing_changed"] is False


def test_same_team_names_in_different_league_do_not_supply_evidence():
    report = compare_coverage(
        {"one": [_entry("123")]},
        _rows(slug="sco.1"),
        "2026-10-09",
    )
    assert report["potential_shadow_ready_count"] == 0
    assert report["state_counts"]["MISSING_COMPETITION_HISTORY"] == 1


def test_future_match_results_cannot_supply_pre_match_features():
    rows = _rows()
    for row in rows:
        row["match_date"] = "2026-10-09"
    report = compare_coverage({"one": [_entry("123")]}, rows, "2026-10-09")
    assert report["potential_shadow_ready_count"] == 0
    assert report["state_counts"]["MISSING_COMPETITION_HISTORY"] == 1


def test_unknown_and_simulated_competition_stays_unmapped():
    report = compare_coverage(
        {"one": [_entry(
            "xyz", competition="Premier League SRL",
            tid="sr:tournament:99999", cid="sr:category:999",
        )]},
        _rows(),
        "2026-10-09",
    )
    assert report["state_counts"]["UNMAPPED_COMPETITION"] == 1


def test_already_modelled_fixture_not_counted_as_new_supply():
    report = compare_coverage(
        {"one": [_entry("123")]},
        _rows(),
        "2026-10-09",
        existing_event_ids=frozenset({"123"}),
    )
    assert report["state_counts"]["ALREADY_MODELLED_FROM_ESPN"] == 1
    assert report["potential_shadow_ready_count"] == 0
