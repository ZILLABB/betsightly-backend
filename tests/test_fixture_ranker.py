import pytest

from leagues.fixture_ranker import canonical_fixture_recommendations


def _pick(market, confidence, odds, *, fixture="f", real=True,
          home_xg=1.5, away_xg=1.5, state="SUPPORTED", implied=None):
    implied = confidence - .02 if implied is None else implied
    return {
        "match_id": fixture, "market": market, "market_group": market,
        "confidence": confidence, "odds": odds, "odds_are_real": real,
        "bookable": True, "expected_value": min(.10, confidence * odds - 1),
        "market_implied_probability": implied, "ml_confidence": confidence - .01,
        "trust": {"evidence_state": state, "evidence_strength": .9,
                  "evidence_adjusted_probability": confidence,
                  "lower_reliability_bound": confidence - .04},
        "_model": {"expected_goals": {"home": home_xg, "away": away_xg,
                                         "total": home_xg + away_xg}},
    }


def test_public_rank_is_recalculated_after_policy_eligibility():
    ranked = canonical_fixture_recommendations([
        _pick("under_2_5", .94, 1.2), _pick("btts_yes", .90, 1.3),
        _pick("over_1_5", .82, 1.4),
    ])
    assert [p["market"] for p in ranked] == ["over_1_5"]
    assert ranked[0]["model_rank"] == 3
    assert ranked[0]["public_rank"] == ranked[0]["fixture_rank"] == 1
    assert ranked[0]["best_model_market"] == "under_2_5"
    assert ranked[0]["best_public_market"] == "over_1_5"


@pytest.mark.parametrize("market", ["home_win", "away_win"])
def test_evidence_supported_straight_win_can_be_public_rank_one(market):
    ranked = canonical_fixture_recommendations([
        _pick(market, .72, 1.45), _pick("over_1_5", .70, 1.3)
    ])
    assert ranked[0]["market"] == market
    assert ranked[0]["public_rank"] == 1
    assert ranked[0]["market_trust_state"] == "TRUSTED"


@pytest.mark.parametrize("change", [
    {"odds_are_real": False}, {"market_implied_probability": .40},
    {"ml_confidence": .40}, {"expected_value": .30},
])
def test_weak_straight_win_remains_rejected(change):
    win = _pick("home_win", .70, 1.5)
    win.update(change)
    ranked = canonical_fixture_recommendations([win, _pick("over_1_5", .68, 1.4)])
    assert all(p["market"] != "home_win" for p in ranked)


def test_min_useful_odds_cannot_create_weaker_team_score_bias():
    ranked = canonical_fixture_recommendations([
        _pick("home_over_0_5", .88, 1.08, home_xg=1.8),
        _pick("away_over_0_5", .73, 1.45, away_xg=1.25),
    ])
    assert [p["market"] for p in ranked] == ["home_over_0_5"]
    assert ranked[0]["odds"] == 1.08


def test_close_quality_secondary_can_survive_but_rank_three_cannot():
    ranked = canonical_fixture_recommendations([
        _pick("over_1_5", .86, 1.10), _pick("under_4_5", .84, 1.16),
        _pick("under_3_5", .81, 1.25),
    ])
    assert [p["fixture_rank"] for p in ranked] == [1, 2]
    assert ranked[0]["selector_version"] == "canonical-recommendations-v1.2"


def test_team_to_score_requires_real_odds_xg_and_confidence_support():
    assert canonical_fixture_recommendations([
        _pick("away_over_0_5", .74, 1.4, real=False, away_xg=.8),
    ]) == []


def test_under_lines_are_independent_and_restricted_line_cannot_block_public_rank():
    ranked = canonical_fixture_recommendations([
        _pick("under_2_5", .92, 1.25), _pick("under_3_5", .84, 1.3),
        _pick("under_4_5", .81, 1.4),
    ])
    assert ranked[0]["market"] == "under_3_5"
    assert ranked[0]["public_rank"] == 1
    assert ranked[0]["model_rank"] > 1


def test_dominated_riskier_fixture_expression_is_removed_structurally():
    ranked = canonical_fixture_recommendations([
        _pick("over_1_5", .82, 1.35),
        _pick("under_4_5", .76, 1.20),
    ])
    assert [pick["market"] for pick in ranked] == ["over_1_5"]
    assert ranked[0]["rejected_fixture_alternatives"][0]["reason"] == (
        "DOMINATED_FIXTURE_EXPRESSION"
    )


def test_feature_flag_preserves_old_selector(monkeypatch):
    original = [_pick("under_2_5", .90, 1.3)]
    monkeypatch.setenv("FIXTURE_RANKED_SELECTOR", "0")
    assert canonical_fixture_recommendations(original) is original
