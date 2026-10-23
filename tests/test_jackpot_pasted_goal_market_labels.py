"""Regression tests for copy/paste market labels in the private jackpot."""

import pytest

from growth.jackpot_market_catalog import resolve_market
from growth.jackpot_paste import parse_fixture_lines


@pytest.mark.parametrize(
    ("label", "market"),
    [
        ("Over 1.5", "over_1_5"),
        ("Over 1.5 Goals", "over_1_5"),
        ("Over 1.5 Goals @1.51", "over_1_5"),
        ("Over 2.5 Goals @1.46", "over_2_5"),
        ("total Over 3.5 goals @ 2.05", "over_3_5"),
        ("Under 2.5 Goals @1.87", "under_2_5"),
    ],
)
def test_common_goal_labels_resolve_to_audited_market(label, market):
    assert resolve_market(label) == market


def test_pasted_fixture_with_goal_suffix_and_reference_price():
    picks = parse_fixture_lines(
        "Olympique Akbou vs CS Constantine | Over 1.5 Goals @1.49\n"
        "FC Den Bosch vs MVV Maastricht | Over 2.5 Goals @1.46"
    )
    assert [row["requested_market"] for row in picks] == [
        "over_1_5", "over_2_5"
    ]
    # The displayed @price is deliberately not carried into pricing/booking.
    assert all("price" not in row and "odds" not in row for row in picks)


def test_unknown_market_is_not_silently_substituted():
    assert resolve_market("Over 7.5 Goals @11.00") is None
