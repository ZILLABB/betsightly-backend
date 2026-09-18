"""Regression for ESPN dates=YYYYMM rather than invalid YYYYMMDD-YYYYMMDD."""
from leagues.score_calendar import collect_monthly_scores, month_keys


def event(home, away, score, date, *, completed=True, event_id="1"):
    return {
        "id": event_id, "date": date,
        "competitions": [{
            "status": {"type": {"completed": completed}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": home}},
                {"homeAway": "away", "team": {"displayName": away}},
            ],
            "score": {"home_score": score[0], "away_score": score[1]},
        }],
    }


def collect(start, end, feed, slugs=None):
    calls = []
    def fetch(slug, month):
        calls.append((slug, month))
        assert len(month) == 6 and month.isdecimal() and "-" not in month
        return feed.get((slug, month), [])
    results = collect_monthly_scores(
        start, end, slugs=slugs or ["esp.1"], fetch_month=fetch,
        regulation_score=lambda comp: comp.get("score"),
        normalize=lambda name: name.casefold().strip(),
    )
    return results, calls


def test_month_boundary_includes_neighboring_month_for_timezone():
    assert month_keys("2026-09-01", "2026-09-01") == ["202608", "202609"]
    assert month_keys("2026-09-30", "2026-09-30") == ["202609", "202610"]


def test_rejects_reversed_date_range():
    import pytest
    with pytest.raises(ValueError):
        month_keys("2026-09-20", "2026-09-10")


def test_month_requests_recover_completed_fixtures_and_exclude_unplayed():
    data = {("esp.1", "202609"): [
        event("Rayo Vallecano", "Espanyol", (2, 1), "2026-09-15T17:00:00Z"),
        event("Alaves", "Valencia", (0, 1), "2026-09-15T18:00:00Z", event_id="2"),
        event("Unknown", "Upcoming", (0, 0), "2026-09-15T22:00:00Z", completed=False),
        event("Outside", "Window", (2, 0), "2026-09-20T22:00:00Z"),
    ]}
    scores, calls = collect("2026-09-15", "2026-09-15", data)
    assert calls == [("esp.1", "202609")]
    assert scores["rayo vallecano|espanyol|2026-09-15"]["home_score"] == 2
    assert scores["alaves|valencia|2026-09-15"]["away_score"] == 1
    assert not any("upcoming" in key or "outside" in key for key in scores)


def test_monthly_collection_keeps_regulation_score_not_penalty_tally():
    data = {("eng.league_cup", "202609"): [event(
        "Peterborough United", "Barnsley", (3, 3), "2026-09-15T18:30:00Z"
    )]}
    scores, _ = collect("2026-09-15", "2026-09-15", data, ["eng.league_cup"])
    assert scores["peterborough united|barnsley|2026-09-15"]["home_score"] == 3


def test_different_same_team_date_fixtures_do_not_get_arbitrary_score():
    data = {("esp.1", "202609"): [
        event("Home", "Away", (0, 1), "2026-09-15T11:00:00Z", event_id="one"),
        event("Home", "Away", (3, 0), "2026-09-15T18:00:00Z", event_id="two"),
    ]}
    scores, _ = collect("2026-09-15", "2026-09-15", data)
    assert "home|away|2026-09-15" not in scores
    assert "home|away" not in scores


def test_duplicate_event_same_identity_does_not_become_ambiguous():
    fixture = event("Home", "Away", (2, 1), "2026-09-15T18:00:00Z")
    data = {("esp.1", "202609"): [fixture, fixture]}
    scores, _ = collect("2026-09-15", "2026-09-15", data)
    assert scores["home|away|2026-09-15"]["home_score"] == 2


def test_provider_failure_is_not_a_fake_result():
    def broken(*_):
        raise TimeoutError("provider unavailable")
    scores = collect_monthly_scores(
        "2026-09-15", "2026-09-15", slugs=["esp.1"], fetch_month=broken,
        regulation_score=lambda c: c.get("score"), normalize=str.casefold,
    )
    assert scores == {}
