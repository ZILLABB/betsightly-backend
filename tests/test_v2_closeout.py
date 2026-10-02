from leagues import v2_closeout


def test_v2_closeout_keeps_challenger_shadow_only(monkeypatch):
    monkeypatch.setattr(
        v2_closeout.builder_runs,
        "summary",
        lambda start, end: {
            "requests": 4,
            "by_mode": [
                {"mode": "target_odds"},
                {"mode": "game_count"},
                {"mode": "strongest"},
                {"mode": "manual"},
            ],
            "by_horizon": [],
            "by_game_count": [],
            "by_fill_strategy": [],
            "by_requested_market": [],
            "by_selected_market": [],
        },
    )

    monkeypatch.setattr(
        v2_closeout.builder_runs,
        "performance",
        lambda days: {
            "builds_generated": 4,
            "unique_settled_builds": 2,
        },
    )

    monkeypatch.setattr(
        v2_closeout.v2_shadow,
        "review_packet",
        lambda: {
            "review_gate": {
                "eligible": False,
                "minimum_settled": 300,
                "current_settled": 3,
                "remaining_to_minimum": 297,
            },
            "evidence": {
                "observations": {
                    "total": 71,
                    "settled": 3,
                    "pending": 68,
                }
            },
            "latest_review": None,
        },
    )

    report = v2_closeout.report(
        days=90,
        start="2026-09-01",
        end="2026-10-02",
    )

    assert report["status"] == "success"
    assert (
        report["builder"]["measurement_contract_ready"]
        is True
    )

    assert set(
        report["builder"]["observed_modes"]
    ) == set(
        v2_closeout.REQUIRED_BUILDER_MODES
    )

    assert (
        report["challenger"]["shadow_only"]
        is True
    )

    assert (
        report["closeout"]
        ["challenger_promotion_is_required_to_close_v2"]
        is False
    )

    assert (
        report["closeout"]
        ["challenger_promotion_ready"]
        is False
    )

    assert (
        report["closeout"]
        ["live_prediction_policy_changed"]
        is False
    )
