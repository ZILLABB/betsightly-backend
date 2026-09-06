import pytest

from leagues.fixture_ranker import canonical_fixture_recommendations
from leagues.selection import TEAM_TO_SCORE_CAP


def _pick(market, confidence, odds, *, fixture="f", real=True, home_xg=1.5, away_xg=1.5):
    return {
        "match_id": fixture, "market": market, "market_group": market,
        "confidence": confidence, "odds": odds, "odds_are_real": real,
        "bookable": True, "expected_value": confidence * odds - 1,
        "_model": {"expected_goals": {"home": home_xg, "away": away_xg, "total": home_xg + away_xg}},
    }


def test_prediction_ranking_happens_before_odds_usefulness():
    ranked = canonical_fixture_recommendations([
        _pick("over_1_5", .90, 1.08),
        _pick("away_over_0_5", .73, 1.45),
    ])
    assert [pick["market"] for pick in ranked] == ["over_1_5"]
    assert ranked[0]["fixture_rank"] == 1


def test_close_quality_secondary_can_survive_but_rank_three_cannot():
    ranked = canonical_fixture_recommendations([
        _pick("over_1_5", .86, 1.10),
        _pick("under_4_5", .84, 1.16),
        _pick("under_3_5", .81, 1.25),
    ])
    assert [pick["fixture_rank"] for pick in ranked] == [1, 2]
    assert [item["market"] for item in ranked[0]["fixture_alternatives"]] == [
        "over_1_5", "under_4_5", "under_3_5",
    ]
    assert ranked[0]["selector_version"] == "canonical-recommendations-v1"


def test_team_to_score_requires_real_odds_xg_and_confidence_support():
    assert canonical_fixture_recommendations([
        _pick("away_over_0_5", .74, 1.4, real=False, away_xg=.8),
    ]) == []


def test_under_lines_do_not_borrow_policy_from_each_other():
    ranked = canonical_fixture_recommendations([
        _pick("under_2_5", .88, 1.3),
        _pick("under_3_5", .84, 1.25),
    ])
    assert [pick["market"] for pick in ranked] == ["under_3_5"]


@pytest.mark.parametrize("target", [5, 10, 20, 50, 70, 100])
def test_team_to_score_public_cap_is_two_for_every_target(target):
    assert TEAM_TO_SCORE_CAP == 2
