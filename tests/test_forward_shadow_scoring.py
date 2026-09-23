from copy import deepcopy

import pytest

from scripts.score_forward_shadow import score


def _archive():
    common = {
        "snapshot_id": "frozen", "fixture_id": "game", "market": "home_win",
        "predicted_at": "2026-09-23T12:00:00+00:00",
        "kickoff_at": "2026-09-24T12:00:00+00:00",
        "observed_odds": 1.7,
        "competition_type": "LEAGUE", "competition_sample": 25,
    }
    return {"snapshot_id": "frozen", "shadow_records": [
        {**common, "model": "devigged_bookmaker", "probability": .60,
         "abstain": False},
        {**common, "model": "poisson_raw", "probability": .70,
         "abstain": False},
        {**common, "model": "trained_ml", "probability": None,
         "abstain": True},
    ]}


def test_forward_forecasts_are_scoreable_only_after_verified_settlement():
    result = score(_archive(), [{"fixture_id": "game", "market": "home_win",
                                 "won": True, "provider": "ESPN",
                                 "verified_at": "2026-09-24T15:00:00+00:00"}])
    assert result["models"]["poisson_raw"]["n"] == 1
    assert result["models"]["poisson_raw"]["brier"] == .09
    assert result["models"]["trained_ml"]["coverage"] == 0
    assert result["models"]["poisson_raw"]["bookmaker_relative"]["n"] == 1


def test_forward_scoring_rejects_leakage_and_duplicates():
    outcomes = [{"fixture_id": "game", "market": "home_win", "won": True,
                 "provider": "ESPN", "verified_at": "2026-09-24T15:00:00+00:00"}]
    early = deepcopy(outcomes)
    early[0]["verified_at"] = "2026-09-24T11:00:00+00:00"
    with pytest.raises(ValueError, match="timing"):
        score(_archive(), early)
    with pytest.raises(ValueError, match="duplicate fixture-market settlement"):
        score(_archive(), outcomes * 2)
    archive = _archive()
    archive["shadow_records"].append(deepcopy(archive["shadow_records"][0]))
    with pytest.raises(ValueError, match="duplicate fixture-market-model"):
        score(archive, outcomes)
