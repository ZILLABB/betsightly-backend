"""Guard the root causes of manual-scores staying unverified for weeks.

All examples are synthetic, with no calls to the sportsbook or score sites.
"""
from datetime import datetime, timezone

from leagues.editorial_settlement import grade_manual_slip
from leagues.results_checker import (
    _known_score_slugs, _lookup_settlement_score, _normalize_name,
)


def test_verified_competition_names_are_resolved_without_manual_slug():
    rows = [
        {"league": "UEFA Champions League"},
        {"league": "UEFA Europa League"},
        {"league": "English Championship"},
    ]
    slugs = _known_score_slugs(rows)
    assert slugs is not None
    assert {"uefa.champions", "uefa.europa", "eng.2"} <= slugs


def test_ambiguous_or_unsupported_manual_league_not_guessed():
    assert _known_score_slugs([
        {"league": "Unknown Country Youth Cup"},
    ]) == set()


def test_one_unmapped_league_does_not_trigger_every_espn_competition():
    # Keep the verified league and avoid the old 90+ scoreboard sweep.
    assert _known_score_slugs([
        {"league": "UEFA Champions League"},
        {"league": "Unknown Country Youth Cup"},
    ]) == {"uefa.champions"}


def test_manual_receipt_team_alias_settles_only_matching_date_and_orientation():
    assert _normalize_name("Man Utd") == _normalize_name("Manchester United")
    now = datetime(2026, 10, 24, 2, tzinfo=timezone.utc)
    leg = {
        "home_team": "Man Utd", "away_team": "Liverpool",
        "kickoff": "2026-10-23T19:00:00Z", "market": "over_1_5",
        "status": "pending",
    }
    record = {"games": [leg], "booking": {"share_code": "IMMUTABLE"},
              "result_status": "pending"}
    scores = {
        "manchester united|liverpool|2026-10-23": {
            "completed": True, "home_score": 2, "away_score": 1,
            "provider": "espn", "provider_event_id": "123",
            "score_90": {"home": 2, "away": 1}, "match_status": "FT",
        }
    }
    result = grade_manual_slip(record, scores, now=now)
    assert result["result_status"] == "won"
    assert result["games"][0]["status"] == "won"
    assert result["booking"] == record["booking"]
    assert grade_manual_slip(record, {
        "manchester united|liverpool|2026-10-22": list(scores.values())[0]
    }, now=now)["result_status"] == "pending"
    assert _lookup_settlement_score(scores, "Liverpool", "Man Utd",
                                    "2026-10-23") is None


def test_unknown_manual_market_stays_pending_even_with_verified_final():
    now = datetime(2026, 10, 24, 2, tzinfo=timezone.utc)
    record = {"games": [{
        "home_team": "Man Utd", "away_team": "Liverpool",
        "kickoff": "2026-10-23T19:00:00Z", "market": "unknown_special",
    }]}
    score = {"manchester united|liverpool|2026-10-23": {
        "home_score": 2, "away_score": 1, "provider": "espn",
        "provider_event_id": "123",
    }}
    graded = grade_manual_slip(record, score, now=now)
    assert graded["result_status"] == "pending"
    assert graded["games"][0]["settlement_pending_reason"] == "UNSUPPORTED_MARKET"


def test_live_event_identity_is_saved_then_only_real_fulltime_can_settle():
    from leagues.editorial_live_link import collect_verified_manual_links

    kickoff = "2026-10-21T16:45:00+00:00"
    game = {
        "match_id": "sportybet:sr:match:74165958",
        "sportybet_event_id": "sr:match:74165958",
        "league": "UEFA Champions League",
        "home_team": "Como 1907", "away_team": "Man Utd",
        "kickoff": kickoff, "market": "home_or_draw",
    }
    live = {
        "espn-live": {
            "source": "espn", "provider_event_id": "401915388",
            "home_team": "Como", "away_team": "Manchester United",
            "kickoff_utc": kickoff, "state": "in",
            "home_score": 1, "away_score": 0,
        }
    }
    calls = []
    def read(slugs, day):
        calls.append((slugs, day))
        return live
    now = datetime(2026, 10, 21, 17, 30, tzinfo=timezone.utc)
    links = collect_verified_manual_links([game], now=now,
                                          score_reader=read)
    assert calls == [(["uefa.champions"], "20261021")]
    assert links[game["match_id"]]["event_id"] == "401915388"
    assert links[game["match_id"]]["score_verified"] is False

    pending = grade_manual_slip({"games": [game]}, {}, now=now,
                                observed_links=links)
    assert pending["result_status"] == "pending"
    assert pending["games"][0]["settlement_source_link"]["event_id"] == "401915388"

    finished = {"espn:event:401915388": {
        "home": "Como", "away": "Manchester United",
        "home_score": 4, "away_score": 1, "date": "2026-10-21",
        "league_slug": "uefa.champions", "provider": "espn",
        "provider_event_id": "401915388",
        "completed": True, "match_status": "STATUS_FULL_TIME",
    }}
    late = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    result = grade_manual_slip(pending, finished, now=late)
    assert result["games"][0]["status"] == "won"
    assert result["result_status"] == "won"
    assert result["games"][0]["settlement_evidence"]["provider"] == "espn"
    assert result["games"][0]["settlement_source_link"]["event_id"] == "401915388"
    assert grade_manual_slip(result, {}, now=late) == result


def test_live_fixture_link_blocks_wrong_kickoff_and_wrong_team():
    from leagues.editorial_live_link import collect_verified_manual_links
    at = datetime(2026, 10, 21, 17, tzinfo=timezone.utc)
    game = {
        "match_id": "sportybet:sr:match:74165958",
        "league": "UEFA Champions League",
        "home_team": "Como 1907", "away_team": "Man Utd",
        "kickoff": "2026-10-21T16:45:00Z", "market": "home_or_draw",
    }
    original = {
        "provider_event_id": "401915388", "source": "espn",
        "home_team": "Como", "away_team": "Manchester United",
        "kickoff_utc": "2026-10-21T16:45:00Z", "state": "pre",
    }
    for wrong in [
        {**original, "home_team": "Manchester United", "away_team": "Como"},
        {**original, "home_team": "Como Women"},
        {**original, "kickoff_utc": "2026-10-22T16:45:00Z"},
    ]:
        assert collect_verified_manual_links(
            [game], now=at, score_reader=lambda *a: {"one": wrong}
        ) == {}
    correct = collect_verified_manual_links(
        [game], now=at, score_reader=lambda *a: {"one": original}
    )
    pending = grade_manual_slip({"games": [game]}, {}, now=at,
                                observed_links=correct)
    conflicting = {"espn:event:401915388": {
        "home": "Como", "away": "Manchester United",
        "date": "2026-10-22", "league_slug": "uefa.champions",
        "home_score": 4, "away_score": 1,
    }}
    result = grade_manual_slip(pending, conflicting,
                               now=datetime(2026, 10, 22, 2,
                                            tzinfo=timezone.utc))
    assert result["result_status"] == "pending"
    assert result["games"][0]["settlement_pending_reason"] == "AMBIGUOUS_FIXTURE"


def test_real_uefa_oct21_recovery_requires_exact_bookmaker_id_and_identity():
    from services.verified_incident_finals import incident_finals
    from leagues.results_checker import _index_free_finals
    at = datetime(2026, 10, 22, 4, tzinfo=timezone.utc)
    fixtures = [
        ("sr:match:74165958", "Como 1907", "Man Utd", "home_or_draw", "won"),
        ("sr:match:74165972", "Betis", "Feyenoord", "home_or_draw", "won"),
        ("sr:match:74165968", "Inter", "Shakhtar D", "home_win", "won"),
        ("sr:match:74165960", "Lille", "Galatasaray Istanbul", "over_1_5", "won"),
        ("sr:match:74165974", "Sporting", "LASK Linz", "home_win", "lost"),
    ]
    games = [
        {
            "sportybet_event_id": event, "home_team": home, "away_team": away,
            "kickoff": "2026-10-21T19:00:00Z", "market": market,
        }
        for event, home, away, market, _ in fixtures
    ]
    verified = incident_finals(games)
    assert len(verified) == 5
    assert all(x["provider"] == "verified-official-fixture-report"
               and x["evidence_url"].startswith("https://www.uefa.com/")
               for x in verified)
    scores = _index_free_finals(verified)
    graded = grade_manual_slip({"games": games}, scores, now=at)
    assert [g["status"] for g in graded["games"]] == [
        expected for _, _, _, _, expected in fixtures
    ]
    assert graded["result_status"] == "lost"
    wrong = {**games[0], "sportybet_event_id": "sr:match:99999"}
    assert incident_finals([wrong]) == []
    changed = {**games[0], "home_team": "Como Women"}
    assert incident_finals([changed]) == []
    previous_day = {**games[0], "kickoff": "2026-10-20T16:45:00Z"}
    assert incident_finals([previous_day]) == []


def test_upcoming_fixture_identity_is_captured_before_kickoff():
    """Do not wait for full time to remember the stable provider event ID."""
    from leagues.editorial_live_link import collect_verified_manual_links
    game = {
        "match_id": "sportybet:sr:match:43214321",
        "league": "UEFA Champions League",
        "home_team": "Como 1907", "away_team": "Man Utd",
        "kickoff": "2026-10-24T19:00:00Z",
        "market": "over_1_5",
    }
    observed = {
        "match": {
            "source": "espn",
            "provider_event_id": "92837465",
            "home_team": "Como", "away_team": "Manchester United",
            "kickoff_utc": "2026-10-24T19:00:00Z",
            "state": "pre",
        },
    }
    links = collect_verified_manual_links(
        [game], now=datetime(2026, 10, 24, 16, tzinfo=timezone.utc),
        score_reader=lambda slugs, day: observed,
    )
    assert links[game["match_id"]]["score_verified"] is False
    pregame = grade_manual_slip({"games": [game]}, {},
                                now=datetime(2026, 10, 24, 16,
                                             tzinfo=timezone.utc),
                                observed_links=links)
    assert pregame["result_status"] == "pending"
    assert pregame["games"][0]["settlement_source_link"]["event_id"] == "92837465"


def test_scoreboard_lookup_is_rate_limited_without_weakening_final_verification(monkeypatch):
    from leagues import editorial_live_link as live
    from leagues import live_scores
    game = {
        "match_id": "sportybet:sr:match:43214321",
        "league": "UEFA Champions League",
        "home_team": "Como 1907", "away_team": "Man Utd",
        "kickoff": "2026-10-24T19:00:00Z",
    }
    observed = {
        "m": {
            "source": "espn", "provider_event_id": "92837465",
            "home_team": "Como", "away_team": "Manchester United",
            "kickoff_utc": "2026-10-24T19:00:00Z",
        },
    }
    calls = []
    monkeypatch.setattr(live, "_LAST_IDENTITY_PROBE", 0.)
    monkeypatch.setattr(live.time, "monotonic", lambda: 1000.)
    monkeypatch.setattr(live_scores, "scores_for",
                        lambda slugs, day: calls.append((slugs, day)) or observed)
    at = datetime(2026, 10, 24, 17, tzinfo=timezone.utc)
    first = live.collect_verified_manual_links([game], now=at)
    assert len(first) == 1 and len(calls) == 1
    second = live.collect_verified_manual_links([game], now=at)
    assert second == {} and len(calls) == 1
    monkeypatch.setattr(live.time, "monotonic", lambda: 1000. + 481)
    third = live.collect_verified_manual_links([game], now=at)
    assert len(third) == 1 and len(calls) == 2


def test_unqualified_manual_premier_league_does_not_claim_england():
    """Legacy receipts have wrong eng.1 slugs for five unrelated countries."""
    from leagues.live_scores import infer_published_competition_slugs
    overseas = [
        ("Geylang International FC", "Hougang United FC"),
        ("FC Ararat-Armenia", "FC Noah Yerevan"),
        ("Maccabi Haifa FC", "Hapoel Be'er Sheva FC"),
        ("Arnett Gardens FC", "Molynes"),
        ("SC Villa", "Blacks Power FC"),
    ]
    for home, away in overseas:
        old_manual = {"home_team": home, "away_team": away,
                      "league": "Premier League",
                      "league_slug": "eng.1", "editorial_manual": True}
        slugs, missing = infer_published_competition_slugs([old_manual])
        assert slugs == set() and missing == 1

    # Even UK teams using this same GENERIC bookmaker label need documented
    # country provenance before an automatic ESPN competition assertion.
    slugs, missing = infer_published_competition_slugs([{
        "home_team": "Liverpool", "away_team": "Brighton",
        "league": "Premier League", "editorial_manual": True,
    }])
    assert slugs == set() and missing == 1
    assert infer_published_competition_slugs([{
        "home_team": "Liverpool", "away_team": "Brighton",
        "league": "English Premier League", "editorial_manual": True,
    }]) == ({"eng.1"}, 0)


def test_official_model_existing_league_slug_unchanged():
    from leagues.live_scores import infer_published_competition_slugs
    assert infer_published_competition_slugs([{
        "league": "Premier League", "league_slug": "eng.1",
        "home_team": "Liverpool", "away_team": "Brighton",
    }]) == ({"eng.1"}, 0)
