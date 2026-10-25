"""Before-tipoff score challenger: frozen 2025 selection, 2026 audit."""
from basketball.research_cli import build_parser
from basketball.research_score_challenger import (
    CONFIGS, _all_variants, challenge, _paired_uncertainty
)
from tests.test_basketball_coldstart import game


def synthetic():
    games = [
        game(10000+i, season=2024, date="2023-11-01", home="1", away="2")
        for i in range(240)]
    games += [
        game(20000+i, season=2025, date="2024-11-01", home="1", away="2")
        for i in range(220)]
    games += [
        game(30000+i, season=2026, date=f"2025-11-{i+1:02}",
             home="1", away="2") for i in range(5)]
    return games


def test_coherent_four_target_forecasts_identical_cohorts():
    rows = _all_variants(synthetic())
    assert len(rows) == 225
    for r in rows:
        for p in r["candidate_variants"].values():
            assert abs(p["predicted_total"]-p["predicted_home_points"]-
                       p["predicted_away_points"]) < 1e-7
            assert abs(p["predicted_home_margin"]-p["predicted_home_points"]+
                       p["predicted_away_points"]) < 1e-7


def test_readonly_and_only_2025_selection(tmp_path):
    games = synthetic()
    original = [dict(x) for x in games]
    result = challenge(games)
    assert result["status"] == "retrospective_comparison_only"
    assert result["hypotheses_predeclared"] == len(CONFIGS)
    assert result["development_2025"]["games"] == 220
    assert result["retrospective_2026"]["games"] == 5
    assert result["model_promotion_approved"] is False
    assert result["genuine_forward_2027_games_used_for_selection"] == 0
    assert result["forecast_archive_or_model_changed"] is False
    assert result["no_writes"] is True
    assert games == original
    assert not list(tmp_path.iterdir())


def test_change_2026_outcomes_cannot_change_2025_selected_model():
    one = synthetic()
    two = [dict(x) for x in one]
    for row in two:
        if row["season"] == 2026:
            row["home_score"], row["away_score"] = (
                row["away_score"], row["home_score"])
    assert (challenge(one)["configuration_selected_using_2025_only"] ==
            challenge(two)["configuration_selected_using_2025_only"])


def test_current_day_finals_do_not_leak():
    cohort = [r for r in _all_variants(synthetic())
              if r["season"] == 2025]
    assert {x["current_home_games"] for x in cohort} == {0}
    assert {x["current_away_games"] for x in cohort} == {0}


def test_missing_cohort_and_no_independent_days():
    assert challenge([])["status"] == "insufficient_2025_development_rows"
    assert _paired_uncertainty([], "total")["status"] == (
        "too_few_independent_dates")
    assert (build_parser().parse_args(
        ["opening-score-challenge"]).command == "opening-score-challenge")
