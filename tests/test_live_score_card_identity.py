"""Conservative live UI identity mapping: no official settlement changes."""
from datetime import datetime, timezone

from leagues.live_scores import align_espn_scores_to_card
from leagues.live_snapshot_cache import _wat_day


def game(mid="published-123", home="Arsenal", away="Chelsea",
         kickoff="2026-10-16T19:00:00Z"):
    return {
        "match_id": mid, "home_team": home, "away_team": away,
        "kickoff": kickoff,
    }


def score(mid="espn-abc", home="Arsenal FC", away="Chelsea",
          kickoff="2026-10-16T19:00:00Z", home_score=2):
    return {mid: {
        "match_id": mid, "home_team": home, "away_team": away,
        "kickoff_utc": kickoff, "home_score": home_score, "away_score": 1,
        "live": True, "finished": False,
    }}


def test_valid_team_and_kickoff_mapping_covers_missing_exact_id():
    original = score()
    found, count = align_espn_scores_to_card(original, [game()])
    assert count == 1
    assert found["published-123"]["home_score"] == 2
    assert found["published-123"]["identity_match"] == "teams_and_kickoff"
    assert found["published-123"]["provisional"] is True
    assert original == score()


def test_exact_id_cannot_be_overwritten_by_fallback():
    original = score(mid="published-123", home="Arsenal")
    found, count = align_espn_scores_to_card(original, [game()])
    assert count == 0
    assert found["published-123"] == original["published-123"]


def test_wrong_date_reverse_teams_and_mismatched_names_fail_closed():
    for mismatch in [
        score(kickoff="2026-10-17T19:00:00Z"),
        score(home="Chelsea", away="Arsenal"),
        score(home="Arsenal U21"),
    ]:
        found, count = align_espn_scores_to_card(mismatch, [game()])
        assert count == 0
        assert "published-123" not in found


def test_more_than_twenty_minutes_from_espn_is_not_accepted():
    found, count = align_espn_scores_to_card(
        score(kickoff="2026-10-16T19:21:00Z"), [game()])
    assert count == 0 and "published-123" not in found


def test_ambiguous_score_candidates_never_guess():
    sources = {
        **score(mid="espn-one"),
        **score(mid="espn-two", home_score=3),
    }
    found, count = align_espn_scores_to_card(sources, [game()])
    assert count == 0 and "published-123" not in found


def test_one_source_cannot_assign_to_two_different_published_fixtures():
    found, count = align_espn_scores_to_card(
        score(), [game(mid="a"), game(mid="b")])
    assert count == 0 and "a" not in found and "b" not in found


def test_timezone_aware_kickoffs_must_align():
    found, count = align_espn_scores_to_card(
        score(kickoff="2026-10-16T20:00:00+01:00"),
        [game(kickoff="2026-10-16T19:00:00Z")])
    assert count == 1 and found["published-123"]["home_score"] == 2


def test_cache_uses_wat_published_card_before_eight():
    assert _wat_day(datetime(2026, 10, 17, 6, 59, tzinfo=timezone.utc)) == "2026-10-16"
    assert _wat_day(datetime(2026, 10, 17, 7, 0, tzinfo=timezone.utc)) == "2026-10-17"
    assert _wat_day(datetime(2026, 10, 16, 23, 30, tzinfo=timezone.utc)) == "2026-10-16"
