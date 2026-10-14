"""Public Telegram product accounting includes manual empty-tier replacements once."""
from growth.editorial_results_report import merge_published_record
from growth import templates


def official():
    return {
        "accounting_version": "contract-v1",
        "won": 11, "lost": 10, "void": 0, "pending": 1,
        "settled": 21, "win_rate": 11 / 21,
        "oldest_pending_date": "2026-10-10",
        "by_category": {
            "banker": {"unit":"published_product", "won": 1,
                       "lost": 1, "void": 0, "pending": 0, "settled": 2},
        },
    }


def editorial(tier, status="lost", day="2026-10-13", odds=5.01):
    return {
        "date": day, "tier": tier, "status": status, "total_odds": odds,
        "editorial_manual": True, "games": [
            {"home_team": "Team A", "away_team": "Team B",
             "market": "over_1_5", "status": "lost"},
        ],
    }


def test_published_tally_counts_manual_replacements_without_modifying_official_record():
    model = official()
    rows = [editorial("2_odds"), editorial("5_odds"), editorial("10_odds", "pending"),
            editorial("over_1_5")]
    report = merge_published_record(
        model, [{"date":"2026-10-13","category":"banker","status":"lost"}],
        rows, as_of="2026-10-13", days=7,
    )
    assert (report["won"],report["lost"],report["pending"],report["settled"]) == (11,13,2,24)
    assert report["manual_editorial"] == {
        "won":0,"lost":3,"void":0,"pending":1,"settled":3,
    }
    assert report["official_model"]["lost"] == 10
    assert model["lost"] == 10
    assert report["by_category"]["over_1_5"]["lost"] == 1


def test_no_double_count_when_model_already_owns_that_date_and_tier():
    rows=[editorial("banker"),editorial("banker"),editorial("2_odds")]
    out=merge_published_record(
        official(), [{"date":"2026-10-13","category":"banker"}],
        rows, as_of="2026-10-13",days=7,
    )
    assert out["lost"] == 11
    assert len(out["editorial_rows"]) == 1


def test_completed_window_excludes_current_and_old_manual_slips():
    rows=[editorial("5_odds",day="2026-10-14"),
          editorial("10_odds",day="2026-09-05"),
          editorial("2_odds",day="2026-10-13")]
    out=merge_published_record(official(),[],rows,as_of="2026-10-13",days=7)
    assert [r["tier"] for r in out["editorial_rows"]] == ["2_odds"]


def test_telegram_results_names_editorial_separately(monkeypatch):
    from growth import templates
    report=merge_published_record(
        official(),[],
        [editorial("2_odds"), editorial("10_odds","pending")],
        as_of="2026-10-13", days=7,
    )
    payload={
        "window_days":7, "won":report["won"],"lost":report["lost"],
        "settled":report["settled"],"pending_products":report["pending"],
        "win_rate":report["win_rate"],
        "editorial_manual_record":report["manual_editorial"],
        "official_model_record":report["official_model"],
        "editorial_reporting_available":True,
        "slips_settled":[{
            "category":"2_odds","label":"2 Odds (Admin-curated)",
            "status":"lost","presentation":"accumulator","total_odds":2.27,
        }],
        "rollover_settled":[],
    }
    result=templates.results({"results":payload},"telegram")
    assert result is not None
    body=result["text"]
    assert "Published slip record" in body
    assert "Admin-curated: 0W" in body
    assert "2 Odds (Admin-curated)" in body
    assert "22 settled" in body
    assert "11W" in body
    assert "not model accuracy" in body


def test_missing_editorial_readback_does_not_claim_complete_public_record():
    report = templates.results({"results":{
        "window_days":7,"won":11,"lost":10,"settled":21,
        "win_rate":11/21,"pending_products":1,"slips_settled":[],
        "rollover_settled":[],"editorial_reporting_available":False,
    }},"telegram")
    assert "totals may be incomplete" in report["text"]
    assert "Every published slip counts" not in report["text"]
