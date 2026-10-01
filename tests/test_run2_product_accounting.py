from leagues import picks_db


def _leg(status, odds=1.20):
    return {
        "status": status,
        "odds": odds,
    }


def _row(
    category,
    status,
    picks,
    presentation="accumulator",
):
    return {
        "date": "2026-09-30",
        "category": category,
        "status": status,
        "presentation": presentation,
        "policy_version": "selection-policy-v1.1",
        "total_odds": 2.0,
        "picks": picks,
    }


def test_over15_counts_once_as_product_but_all_legs_as_picks(
    monkeypatch,
):
    history = [
        _row(
            "over_1_5",
            "won",
            [_leg("won")] * 9 + [_leg("lost")],
            "singles",
        ),
        _row(
            "2_odds",
            "lost",
            [_leg("lost")],
        ),
    ]

    monkeypatch.setattr(
        picks_db,
        "get_history",
        lambda limit_days: history,
    )

    monkeypatch.setattr(
        picks_db,
        "_booking_records",
        lambda cutoff: {},
    )

    products = (
        picks_db.product_performance_summary(7)
    )

    picks = (
        picks_db.performance_summary(7)
    )

    assert products["won"] == 1
    assert products["lost"] == 1
    assert products["settled"] == 2

    assert (
        products["by_category"]
        ["over_1_5"]
        ["settled"]
        == 1
    )

    assert (
        picks["over_1_5"]["unit"]
        == "pick"
    )

    assert (
        picks["over_1_5"]["won"]
        == 9
    )

    assert (
        picks["over_1_5"]["lost"]
        == 1
    )

    assert (
        picks["over_1_5"]["settled"]
        == 10
    )


def test_pending_product_does_not_become_loss(
    monkeypatch,
):
    history = [
        _row(
            "banker",
            "won",
            [_leg("won")],
        ),
        _row(
            "over_1_5",
            "pending",
            [_leg("won"), _leg("pending")],
            "singles",
        ),
    ]

    monkeypatch.setattr(
        picks_db,
        "get_history",
        lambda limit_days: history,
    )

    record = (
        picks_db.product_performance_summary(7)
    )

    assert record["won"] == 1
    assert record["lost"] == 0
    assert record["settled"] == 1
    assert record["pending"] == 1


def test_product_window_can_end_on_completed_day(
    monkeypatch,
):
    calls = []

    def fake_history(
        limit_days=30,
        category=None,
        as_of=None,
    ):
        calls.append(as_of)
        return []

    monkeypatch.setattr(
        picks_db,
        "get_history",
        fake_history,
    )

    result = (
        picks_db.product_performance_summary(
            7,
            as_of="2026-09-30",
        )
    )

    assert result["settled"] == 0
    assert calls == ["2026-09-30"]
