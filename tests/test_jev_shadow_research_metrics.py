from datetime import datetime, timedelta, timezone
import pytest

from basketball.jev_research_evidence import (
    basketball_shadow_envelope, basketball_research_status,
)
from leagues.jev_shadow_evaluation import review_settled_labels

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def forecast(**changes):
    return {
        "competition": "NBA", "game_id": "nba-100",
        "home_team": "Boston Celtics", "away_team": "New York Knicks",
        "market": "nba_moneyline", "tipoff_utc": (NOW + timedelta(hours=6)).isoformat(),
        "original_model_probability": .68, "original_bookmaker_price": 1.65,
        "original_pregame_forecast": True, "verified_fixture_identity": True,
        **changes,
    }


def observation(timestamp=None):
    return {"type": "competition_schedule", "source_id": "nba-official-game-100",
            "source_url": "https://nba.com/schedule", "claim": "Game upcoming",
            "observed_at": (timestamp or NOW).isoformat()}


def test_nba_research_is_before_tipoff_and_never_publishes():
    result = basketball_shadow_envelope(forecast(), [observation()], as_of=NOW)
    assert result["status"] == "ready_for_shadow_review"
    assert result["state"]["sport"] == "basketball"
    assert result["research_scope"] == "nba_private_only"
    assert result["publication_authority"] is False
    assert result["betting_code_generated"] is False


@pytest.mark.parametrize("changes,expected", [
    ({"competition": "WNBA"}, "unsupported_league"),
    ({"competition": "NCAA"}, "unsupported_league"),
    ({"competition": "EuroLeague"}, "unsupported_league"),
    ({"market": "unsupported_parlay"}, "unsupported_market"),
    ({"tipoff_utc": (NOW - timedelta(minutes=1)).isoformat()}, "ineligible"),
    ({"original_pregame_forecast": False}, "ineligible"),
    ({"verified_fixture_identity": False}, "ineligible"),
])
def test_basketball_unsupported_sources_never_auto_promote(changes, expected):
    assert basketball_shadow_envelope(
        forecast(**changes), [observation()], as_of=NOW)["status"] == expected


def test_future_injury_update_not_backdated_for_basketball():
    result = basketball_shadow_envelope(
        forecast(), [observation(NOW + timedelta(hours=1))], as_of=NOW)
    assert result["evidence_count"] == 0
    assert result["rejected_evidence"]["future_or_post_kickoff"] == 1


def test_league_status_is_explicitly_not_promoted():
    status = basketball_research_status()
    assert status["WNBA"] == "coverage_not_yet_accepted"
    assert status["separate_from_football"] is True


def label(fid, mkt, choice, outcome):
    return {
        "fixture_id": fid, "market": mkt,
        "predicted_probability": .65, "jev_evidence_state": choice,
        "verified_outcome": outcome, "pregame_captured": True,
        "verified_settlement": True,
    }


def test_empty_outcome_sample_never_invents_jev_accuracy():
    result = review_settled_labels([])
    assert result["total_verified"] == 0
    assert result["baseline"]["brier"] is None
    assert result["promotion_allowed"] is False


def test_held_out_summary_reports_false_withholds_and_real_probabilities():
    rows = [label("1", "over_1_5", "supported", 1),
            label("2", "over_1_5", "conflicted", 1),
            label("3", "over_1_5", "insufficient", 0),
            label("4", "btts", "supported", 0)]
    result = review_settled_labels(rows)
    assert result["total_verified"] == 4
    assert result["baseline"]["count"] == 4
    assert result["jev_supported"]["count"] == 2
    assert result["false_withhold_wins"] == 1
    assert result["supported_coverage"] == .5
    assert result["sample_ready"] is False
    assert result["promotion_allowed"] is False


def test_never_count_unverified_hindsight_or_duplicated_training_rows():
    first = label("1", "home_win", "supported", 1)
    second = label("2", "home_win", "conflicted", 0)
    second["verified_settlement"] = False
    third = label("3", "home_win", "supported", 1)
    third["pregame_captured"] = False
    result = review_settled_labels([first, first, second, third])
    assert result["total_verified"] == 1
    assert result["rejected"]["ineligible_or_duplicate"] == 3


def test_cannot_lower_minimum_holdout_to_claim_success():
    with pytest.raises(ValueError):
        review_settled_labels([label("1", "btts", "supported", 1)],
                              min_holdout=10)
