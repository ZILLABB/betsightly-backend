"""Manual league discovery must never silently guess another competition."""
from leagues.live_scores import infer_published_competition_slugs


def test_manual_bookmaker_league_without_slug_gets_correct_supported_competition():
    slugs, unknown=infer_published_competition_slugs([
        {"match_id":"sportybet:123","league":"UEFA Champions League"},
        {"match_id":"sportybet:234","league":"Premier League"},
        {"match_id":"sportybet:345","league":"English Premier League"},
    ])
    assert "uefa.champions" in slugs
    assert "eng.1" in slugs
    assert unknown == 0


def test_unknown_competition_is_not_relabelled_as_another_league():
    slugs, unknown=infer_published_competition_slugs([
        {"league":"English Women's Youth Cup"},
        {"league":"Unknown friendly tournament"},
        {"league":"Serie C"},
    ])
    assert not slugs and unknown == 3


def test_known_slug_takes_priority_even_with_different_presentation_label():
    slugs,unknown=infer_published_competition_slugs([
        {"league_slug":"esp.1","league":"Spain"}
    ])
    assert slugs == {"esp.1"} and unknown == 0
