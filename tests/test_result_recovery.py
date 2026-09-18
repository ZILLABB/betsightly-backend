"""Deterministic recovery tests: no API/network/database required."""
from datetime import datetime, timezone, timedelta
import unicodedata
import re

from leagues.result_recovery import recover_missing_espn_scores

NOW = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)


def norm(name):
    normalized = unicodedata.normalize("NFKD", name.casefold())
    return " ".join(re.sub(r"[^\w]+", " ",
                   "".join(c for c in normalized if not unicodedata.combining(c))).split())


def lookup(scores, home, away, date):
    return scores.get(f"{norm(home)}|{norm(away)}|{date}")


def pick(home="Alavés", away="Valencia", slug="esp.1", kickoff="2026-09-15T18:00:00Z"):
    return dict(home_team=home, away_team=away, league_slug=slug,
                commence_time=kickoff, status="pending")


def event(home="Alaves", away="Valencia", score=(0, 1), kickoff="2026-09-15T18:00:00Z",
          completed=True, event_id="x", extra=None):
    return {"id": event_id, "date": kickoff, "competitions": [{
        "status": {"type": {"completed": completed}},
        "competitors": [
            {"homeAway": "home", "team": {"displayName": home}},
            {"homeAway": "away", "team": {"displayName": away}},
        ], "_regulation": dict(home_score=score[0], away_score=score[1],
                              score_90={"home": score[0], "away": score[1]},
                              **(extra or {})),
    }]}


def recover(picks, fetch, initial=None, now=NOW, max_queries=48):
    return recover_missing_espn_scores(
        picks, initial or {}, known_slugs={"esp.1", "eng.league_cup"},
        fetch_events=fetch, regulation_score=lambda c: c.get("_regulation"),
        normalize=norm, lookup_score=lookup, now=now, max_queries=max_queries,
    )


def test_accent_and_away_win_from_confirmed_regulation_score():
    calls = []
    def fetch(slug, day):
        calls.append((slug, day)); return [event()]
    got = recover([pick()], fetch)
    assert lookup(got, "Alavés", "Valencia", "2026-09-15")["away_score"] == 1
    assert calls == [("esp.1", "20260915")]


def test_reject_wrong_opponent_or_reversed_home_away():
    got = recover([pick()], lambda *_: [event(home="Valencia", away="Alaves")])
    assert got == {}


def test_reject_rematch_outside_kickoff_window():
    got = recover([pick()], lambda *_: [event(kickoff="2026-09-16T18:00:00Z")])
    assert got == {}


def test_skip_unverified_league_and_future_games():
    calls = []
    def fetch(*a): calls.append(a); return []
    assert recover([pick(slug="unknown"), pick(kickoff="2026-09-18T10:00:00Z")], fetch) == {}
    assert calls == []


def test_does_not_overwrite_an_existing_score():
    initial = {"alaves|valencia|2026-09-15": {"home_score": 0, "away_score": 2}}
    called = []
    def fetch(*a): called.append(a); return [event()]
    got = recover([pick()], fetch, initial)
    assert got == initial and not called


def test_retry_adjacent_provider_day_and_respect_cap():
    calls = []
    def fetch(slug, day):
        calls.append(day)
        return [event()] if day == "20260914" else []
    got = recover([pick()], fetch)
    assert lookup(got, "Alaves", "Valencia", "2026-09-15") is not None
    assert calls == ["20260915", "20260914"]
    assert recover([pick()], lambda *_: [], max_queries=1) == {}


def test_reject_unfinished_and_conflicting_events():
    assert recover([pick()], lambda *_: [event(completed=False)]) == {}
    a, b = event(score=(0, 1), event_id="a"), event(score=(1, 0), event_id="b")
    assert recover([pick()], lambda *_: [a, b]) == {}


def test_uses_regulation_not_penalties_and_does_not_make_up_voids():
    cup = pick("Peterborough United", "Barnsley", "eng.league_cup", "2026-09-15T18:30:00Z")
    got = recover([cup], lambda *_: [event("Peterborough United", "Barnsley", (3, 3),
                                 "2026-09-15T18:30:00Z", extra={"penalty_score": {"home": 5, "away": 4}})])
    assert lookup(got, "Peterborough United", "Barnsley", "2026-09-15")["home_score"] == 3
    assert recover([cup], lambda *_: []) == {}


def test_fetches_independent_competitions_concurrently():
    from threading import Barrier
    barrier = Barrier(2)
    picks = [pick(), pick(home="Peterborough United", away="Barnsley",
                          slug="eng.league_cup", kickoff="2026-09-15T18:30:00Z")]
    def fetch(slug, day):
        if day != "20260915":
            return []
        barrier.wait(timeout=2)
        return [event()] if slug == "esp.1" else [event(
            "Peterborough United", "Barnsley", (3, 3),
            "2026-09-15T18:30:00Z")]
    got = recover(picks, fetch)
    assert lookup(got, "Alaves", "Valencia", "2026-09-15")
    assert lookup(got, "Peterborough United", "Barnsley", "2026-09-15")


def test_rotating_budget_eventually_checks_other_pending_fixtures():
    picks = [pick(home=f"Home{i}", away=f"Away{i}",
                  kickoff=f"2026-09-{15-i:02d}T18:00:00Z") for i in range(4)]
    requested = set()
    for hour in range(4):
        now = NOW + timedelta(hours=hour)
        def fetch(slug, day):
            requested.add(day)
            return []
        recover(picks, fetch, now=now, max_queries=1)
    assert {"20260912", "20260913", "20260914", "20260915"} <= requested
