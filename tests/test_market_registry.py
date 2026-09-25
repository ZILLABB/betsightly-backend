"""Executable contract between modeled, selectable, bookable and settleable markets."""
import pytest

from leagues import evidence_fusion, fixture_ranker, historical_replay, picks, sportybet
from leagues.base_rates import GLOBAL_DEFAULTS
from leagues.market_registry import MARKETS, capability_matrix
from leagues.predictor import _p_over, predict
from leagues.results_checker import _evaluate_pick


SHADOW_MAPPED = {"over_4_5", "home_under_0_5", "home_under_1_5",
                 "away_under_0_5", "away_under_1_5"}


def test_registry_is_the_mapping_and_policy_source():
    assert len(MARKETS) == len(set(MARKETS)) == 26
    assert picks.MARKET_LABELS == {k: s.label for k, s in MARKETS.items()
                                    if s.model_sources}
    assert picks.MARKET_GROUP == {k: s.group for k, s in MARKETS.items()
                                   if s.model_sources}
    assert picks.CALIBRATION_GROUP == {k: s.calibration_group
                                       for k, s in MARKETS.items() if s.model_sources}
    assert sportybet.MARKET_TO_SPORTYBET == {k: s.sportybet
                                             for k, s in MARKETS.items() if s.sportybet}
    assert fixture_ranker.TRUSTED_MARKETS == {k for k, s in MARKETS.items()
                                               if s.public_policy == "TRUSTED"}
    assert evidence_fusion.RESTRICTED == {k for k, s in MARKETS.items()
                                           if s.evidence_policy == "RESTRICTED"}
    assert set(historical_replay.MARKETS) == {k for k, s in MARKETS.items()
                                               if s.replay}
    assert MARKETS["under_3_5"].activation == "SHADOW"
    assert "under_3_5" not in fixture_ranker.TRUSTED_MARKETS


def test_active_market_has_all_required_capabilities():
    for key, spec in MARKETS.items():
        assert key == spec.key
        assert spec.label and spec.group and spec.exposure
        if spec.activation != "ACTIVE":
            assert not spec.builder and not spec.safe_tier and not spec.booking
            continue
        assert spec.model_sources and spec.calibration_group
        assert spec.settlement and spec.replay
        assert spec.sportybet and spec.booking
        assert spec.public_policy not in {"RESTRICTED", "DISABLED"}
        assert spec.evidence_policy == "PROMOTED"
        assert _evaluate_pick({"market_key": key}, 2, 1) != "pending"


def test_mapped_shadow_market_cannot_enter_public_or_builder():
    assert SHADOW_MAPPED <= set(MARKETS)
    for key in SHADOW_MAPPED:
        spec = MARKETS[key]
        assert spec.sportybet and spec.model_sources and spec.settlement and spec.replay
        assert spec.activation == "SHADOW"
        assert not spec.candidate_generation and not spec.builder and not spec.booking
    matrix = {row["key"]: row for row in capability_matrix()}
    assert set(matrix) == set(MARKETS)
    assert not matrix["over_4_5"]["public"]
    assert not matrix["over_4_5"]["exact_booking"]


def test_shadow_probabilities_are_coherent_and_absent_from_public_candidates():
    model = predict({"odds": {}}, GLOBAL_DEFAULTS)
    public = model["probabilities"]
    shadow = model["shadow_probabilities"]
    home = model["expected_goals"]["home"]
    away = model["expected_goals"]["away"]
    assert set(shadow) == SHADOW_MAPPED
    assert not set(shadow) & set(public)
    assert all(0 <= value <= 1 for value in shadow.values())
    # Expected goals are rounded for display, hence the small comparison tolerance.
    assert shadow["home_under_0_5"] == pytest.approx(
        1 - _p_over(.5, home), abs=.004)
    assert shadow["away_under_1_5"] == pytest.approx(
        1 - _p_over(1.5, away), abs=.004)
    assert shadow["over_4_5"] == pytest.approx(
        _p_over(4.5, home + away), abs=.004)
    assert shadow["home_under_0_5"] <= shadow["home_under_1_5"]
    assert shadow["away_under_0_5"] <= shadow["away_under_1_5"]


@pytest.mark.parametrize("market,score,expected", [
    ("over_4_5", (3, 2), "won"),
    ("over_4_5", (2, 2), "lost"),
    ("home_under_0_5", (0, 2), "won"),
    ("home_under_0_5", (1, 0), "lost"),
    ("home_under_1_5", (1, 2), "won"),
    ("away_under_0_5", (2, 0), "won"),
    ("away_under_1_5", (2, 1), "won"),
    ("dnb_home", (1, 1), "void"),
])
def test_mapped_shadow_and_dnb_settlement(market, score, expected):
    assert _evaluate_pick({"market_key": market}, *score) == expected
    replay = historical_replay.settle_markets(*score)[market]
    assert replay == {"won": 1, "lost": 0, "void": None}[expected]
