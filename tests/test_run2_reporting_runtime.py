import asyncio

from growth import dataset
from growth.templates import (
    results as render_results,
)
from leagues import (
    api,
    engine,
    picks_db,
    results_checker,
    scheduler,
)


def test_results_dataset_uses_completed_day_window(
    monkeypatch,
):
    calls = {
        "history": [],
        "performance": [],
        "products": [],
    }

    def fake_history(
        limit_days=30,
        category=None,
        as_of=None,
    ):
        calls["history"].append(
            as_of
        )
        return []

    def fake_performance(
        limit_days=90,
        policy_version=None,
        as_of=None,
    ):
        calls["performance"].append(
            as_of
        )
        return {}

    def fake_products(
        limit_days=90,
        policy_version=None,
        as_of=None,
    ):
        calls["products"].append(
            as_of
        )

        return {
            "accounting_version":
                "published-product-v1",
            "unit":
                "published_product",
            "won": 0,
            "lost": 0,
            "void": 0,
            "pending": 0,
            "settled": 0,
            "win_rate": None,
            "oldest_pending_date": None,
            "by_category": {},
        }

    monkeypatch.setattr(
        picks_db,
        "get_history",
        fake_history,
    )

    monkeypatch.setattr(
        picks_db,
        "performance_summary",
        fake_performance,
    )

    monkeypatch.setattr(
        picks_db,
        "product_performance_summary",
        fake_products,
    )

    monkeypatch.setattr(
        "leagues.rollover_db.history",
        lambda limit_days=7: [],
    )

    result = dataset._recent_results(
        days=7
    )

    assert result["window_end"]

    assert (
        calls["history"][0]
        == calls["performance"][0]
        == calls["products"][0]
        == result["window_end"]
    )


def test_telegram_reports_official_slips_without_individual_pick_record():
    payload = render_results(
        {
            "results": {
                "window_days": 7,
                "won": 17,
                "lost": 11,
                "settled": 28,
                "win_rate": 17 / 28,
                "pending_products": 1,

                "slips_settled": [
                    {
                        "label":
                            "Over 1.5",
                        "status":
                            "won",
                        "presentation":
                            "singles",
                        "leg_won":
                            9,
                        "leg_lost":
                            1,
                        "total_odds":
                            0,
                    }
                ],

                "rollover_settled":
                    [],

                "singles": {
                    "won": 41,
                    "lost": 9,
                    "settled": 50,
                    "win_rate": 41 / 50,
                },
            }
        },
        "telegram",
    )

    text = payload["text"]

    assert "✅ Won: *17*" in text
    assert "❌ Lost: *11*" in text

    assert (
        "Slip strike rate: "
        "*61%* (28 settled)"
        in text
    )

    assert (
        "Over 1.5 — 9/10 selections"
        in text
    )

    assert "Individual picks:" not in text
    assert "41 from 50" not in text

    assert "Results so far" in text

    assert (
        "1 published product is "
        "still awaiting a verified "
        "final score"
        in text
    )
    assert "📊 *BetSightly Results*" in text
    assert "_Every published slip counts — wins and losses._" in text


def test_telegram_results_uses_plural_pending_product_wording():
    payload = render_results(
        {
            "results": {
                "window_days": 7,
                "won": 1,
                "lost": 1,
                "settled": 2,
                "win_rate": .5,
                "pending_products": 2,
                "slips_settled": [],
                "rollover_settled": [],
            }
        },
        "telegram",
    )

    assert "2 published products are still awaiting a verified final score." in payload["text"]
    assert "⏳ Pending: *2*" in payload["text"]


def test_runtime_status_reports_process_ownership(
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "production",
    )

    monkeypatch.setenv(
        "ENABLE_BACKGROUND_JOBS",
        "true",
    )

    monkeypatch.setenv(
        "BETSIGHTLY_PROCESS_ROLE",
        "web",
    )

    monkeypatch.setattr(
        results_checker,
        "settlement_status",
        lambda: {
            "poll_seconds":
                900,
            "fallback_seconds":
                3600,
            "last_successful_check":
                None,
        },
    )

    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda days_ahead=7: {
            "ready": True,
            "degraded": False,
            "complete": True,
            "age_seconds": 12,
            "source": "persistence",
            "provider": {
                "complete": True,
            },
        },
    )

    monkeypatch.setattr(
        scheduler,
        "last_runs",
        lambda limit=3: [
            {
                "status":
                    "complete"
            }
        ],
    )

    result = asyncio.run(
        api.get_runtime_status()
    )

    assert (
        result["process"]["role"]
        == "web"
    )

    assert (
        result["process"][
            "owns_scheduler"
        ]
        is False
    )

    assert (
        result["process"][
            "owns_settlement"
        ]
        is False
    )

    assert (
        result["prepared_board"][
            "ready"
        ]
        is True
    )

    assert (
        result["settlement"][
            "poll_seconds"
        ]
        == 900
    )


def test_settlement_status_reports_polling_cadence():
    status = (
        results_checker
        .settlement_status()
    )

    assert (
        status["poll_seconds"]
        == 900
    )

    assert (
        status["fallback_seconds"]
        >= 3600
    )
