from datetime import date

import pytest

from leagues.chronological_split import (
    describe_whole_date_split,
    whole_date_boundaries,
)


def test_boundaries_never_split_a_calendar_date():
    dates = (
        [date(2026, 1, 1)] * 6
        + [date(2026, 1, 2)] * 6
        + [date(2026, 1, 3)] * 6
        + [date(2026, 1, 4)] * 6
        + [date(2026, 1, 5)] * 6
    )
    plan = describe_whole_date_split(dates)

    assert plan["train"] + plan["calib"] + plan["test"] == len(dates)
    assert plan["train_end"] != plan["calib_start"]
    assert plan["calib_end"] != plan["test_start"]
    assert plan["train_calib_same_date_boundary"] is False
    assert plan["calib_test_same_date_boundary"] is False


def test_boundary_moves_to_complete_date_group():
    dates = (
        [date(2026, 1, 1)] * 4
        + [date(2026, 1, 2)] * 4
        + [date(2026, 1, 3)] * 4
        + [date(2026, 1, 4)] * 4
        + [date(2026, 1, 5)] * 4
    )
    i_tr, i_ca = whole_date_boundaries(dates)

    assert i_tr in {4, 8, 12, 16}
    assert i_ca in {4, 8, 12, 16}
    assert dates[i_tr - 1] != dates[i_tr]
    assert dates[i_ca - 1] != dates[i_ca]


def test_requires_three_distinct_dates():
    with pytest.raises(ValueError):
        whole_date_boundaries(
            [date(2026, 1, 1)] * 5 + [date(2026, 1, 2)] * 5
        )
