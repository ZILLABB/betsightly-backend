"""An empty target cannot be presented as proof of fixture scarcity."""

from leagues.daily_feed import _select_tier


def test_empty_tier_names_selection_constraints_without_claiming_no_matches():
    selection, reason = _select_tier(
        [], 2.0, 4, 0.65, 0.82, canonicalize=False,
    )
    assert selection == ([], 0.0, 0.0)
    assert "prediction, price and slip-quality rules" in reason
    assert "Not enough matches" not in reason
