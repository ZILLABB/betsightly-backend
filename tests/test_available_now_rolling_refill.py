"""Rolling Available Now refills must not rewrite official prediction history."""
from datetime import datetime, timedelta, timezone

from leagues import daily_feed


def _pick(match_id, kickoff, market="home_win"):
    return {
        "match_id": match_id, "market": market, "market_group": market,
        "prediction": "Home Win", "odds": 1.5, "confidence": .8,
        "bookable": True, "odds_are_real": True,
        "_fixture": {
            "match_id": match_id,
            "commence_time": kickoff.isoformat().replace("+00:00", "Z"),
            "home": {"name": f"Home {match_id}"},
            "away": {"name": f"Away {match_id}"},
        },
    }


def _wire(monkeypatch):
    from leagues import selection, fixture_ranker, publication_policy
    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations",
        lambda pool, **kwargs: list(pool),
    )
    monkeypatch.setattr(
        daily_feed, "filter_official_candidates",
        lambda pool, product: (list(pool), []),
    )
    monkeypatch.setattr(
        daily_feed, "_build_rollover",
        lambda *a, **kw: {"selected": False, "games": [], "chain": []},
    )
    monkeypatch.setattr(selection, "select_banker", lambda *a, **kw: ([], 0, 0))
    monkeypatch.setattr(publication_policy, "enforce_card_policy", lambda acc: {})
    monkeypatch.setattr(daily_feed, "enforce_card_policy", lambda acc: {})
    monkeypatch.setattr(
        "leagues.picks.to_game",
        lambda p: dict(p, home_team=p["_fixture"]["home"]["name"],
                       away_team=p["_fixture"]["away"]["name"],
                       kickoff=p["_fixture"]["commence_time"]),
    )


def test_rolling_live_refill_only_uses_future_30_hour_window(monkeypatch):
    _wire(monkeypatch)
    now = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    picks = [
        _pick("started", now - timedelta(hours=1)),
        _pick("buffer", now + timedelta(minutes=10)),
        _pick("today", now + timedelta(hours=2)),
        _pick("tomorrow", now + timedelta(hours=28)),
        _pick("outside", now + timedelta(hours=31)),
    ]
    calls = []

    def selector(pool, target, max_picks, min_confidence, min_ev, **kwargs):
        calls.append((target, max_picks, kwargs.get("band_low"), {
            p["match_id"] for p in pool
        }))
        return ([], 0, 0), "no qualifying combo"

    monkeypatch.setattr(daily_feed, "_select_tier", selector)
    monkeypatch.setattr(
        "leagues.sportybet.fetch_board",
        lambda: (_ for _ in ()).throw(AssertionError("no bookings for empty card")),
    )
    result = daily_feed.build_bookable_now(all_picks=picks, now=now)
    assert result["published_record_unchanged"] is True
    assert result["rolling_window_hours"] == 30
    assert result["kickoffs_remaining"] == 2
    assert {x[0] for x in calls} == {2.0, 5.0, 10.0}
    assert all(x[3] == {"today", "tomorrow"} for x in calls)
    assert next(x for x in calls if x[0] == 5.0)[1] == 20
    ten = next(x for x in calls if x[0] == 10.0)
    assert ten[1] == 20 and ten[2] == 1.0


def test_no_bookmaker_io_when_live_policy_withholds_all(monkeypatch):
    _wire(monkeypatch)
    now = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
    pick = _pick("future", now + timedelta(hours=3))

    def selector(pool, target, *args, **kwargs):
        return ((list(pool), 1.5, .8), None) if target == 2.0 else (([], 0, 0), None)

    monkeypatch.setattr(daily_feed, "_select_tier", selector)

    def withhold(card):
        for tier in card.values():
            tier.update(selected=False, games=[], total_odds=0, hit_probability=0)
        return {}

    monkeypatch.setattr(daily_feed, "enforce_card_policy", withhold)
    monkeypatch.setattr(
        "leagues.sportybet.fetch_board",
        lambda: (_ for _ in ()).throw(AssertionError("policy-invalid code request")),
    )
    result = daily_feed.build_bookable_now(all_picks=[pick], now=now)
    assert result["available"] is False
    assert not result["accumulators"]["2_odds"]["games"]


def test_live_ten_odds_refuses_code_below_ten_after_readback(monkeypatch):
    _wire(monkeypatch)
    now = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
    picks = [_pick(str(i), now + timedelta(hours=3+i)) for i in range(7)]

    def selector(pool, target, *args, **kwargs):
        return ((list(pool), 17.09, .2), None) if target == 10.0 else (([], 0, 0), None)

    monkeypatch.setattr(daily_feed, "_select_tier", selector)
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: {})

    def attach(card, board):
        card["10_odds"]["booking"] = {
            "status": "active", "booking_status": "FULL",
            "readback_validation": "PASSED", "share_code": "NOT_ACTIONABLE",
            "actual_sportybet_odds": 9.80,
        }

    monkeypatch.setattr(daily_feed, "_attach_live_bookings", attach)
    result = daily_feed.build_bookable_now(all_picks=picks, now=now)
    ten = result["accumulators"]["10_odds"]
    assert ten["selected"] is False
    assert not ten["games"]
    assert "10.00x" in ten["reason"]
    assert result["available"] is False
