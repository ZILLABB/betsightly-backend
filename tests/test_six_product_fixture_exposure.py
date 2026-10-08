"""All six daily products reserve a fixture at most once."""
from datetime import datetime, timedelta, timezone

from leagues import daily_feed
from scripts import preview_staging_official_card


def _card(**tiers):
    card = {
        key: {"selected": False, "games": []}
        for key in daily_feed.ALL_DAILY_PRODUCT_NAMES
    }
    card.update(tiers)
    return card


def _games(*ids):
    return [{"match_id": match_id} for match_id in ids]


def test_all_six_product_uniqueness_detects_over_1_5_against_accumulators():
    card = _card(
        banker={"selected": True, "games": _games("one")},
        **{
            "2_odds": {"selected": True, "games": _games("two")},
            "5_odds": {"selected": True, "games": _games("three")},
            "over_1_5": {"selected": True, "games": _games("one", "four")},
        },
    )
    assert daily_feed.all_daily_fixture_conflicts(card) == [
        {"match_id": "one", "products": ["banker", "over_1_5"]}
    ]
    card["over_1_5"]["games"] = _games("four")
    assert daily_feed.all_daily_fixture_conflicts(card) == []


def test_all_six_product_uniqueness_detects_repeat_inside_singles():
    card = _card(over_1_5={"selected": True, "games": _games("x", "x")})
    assert daily_feed.all_daily_fixture_conflicts(card) == [
        {"match_id": "x", "products": ["over_1_5", "over_1_5"]}
    ]


def test_official_preview_fails_closed_with_actionable_conflict_names(monkeypatch):
    from leagues import daily_feed as feed
    from leagues import engine

    now = datetime.now(timezone.utc)
    date = (now + timedelta(days=1)).date().isoformat()
    kickoff = f"{date}T20:00:00Z"
    picks = [{
        "match_id": "fixture-one",
        "_fixture": {"commence_time": kickoff},
    }]
    fixtures = [{"match_id": "fixture-one", "commence_time": kickoff}]
    monkeypatch.setattr(
        preview_staging_official_card, "preflight",
        lambda: "betsightly_db_staging",
    )
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: (picks, fixtures, {
            "ready": True, "stale": False, "complete": True,
            "board_snapshot_id": "simulated",
            "age_seconds": 0,
        }),
    )
    def build(preview):
        assert preview["target_wat_date"] == date
        return {
            "locked": False, "fixture_target_date": date,
            "accumulators": _card(
                banker={"selected": True, "games": [
                    {"match_id": "fixture-one", "home_team": "A",
                     "away_team": "B", "market": "over_1_5"},
                ]},
                over_1_5={"selected": True, "games": [
                    {"match_id": "fixture-one", "home_team": "A",
                     "away_team": "B", "market": "over_1_5"},
                ]},
            ),
        }
    monkeypatch.setattr(feed, "build_daily_accumulators", build)
    import pytest
    with pytest.raises(RuntimeError, match="fixture-one.*over_1_5"):
        preview_staging_official_card.simulate(target_date_wat=date)
