"""EuroLeague/EuroCup settlement: exact evidence, eight-leg ticket, no guesses."""
from datetime import datetime, timezone

import pytest

from growth import basketball_europe_finals as europe
from growth import basketball_settlement as bs
from growth import basketball_history as history


def official(game_code, home, away, h, a, when, *, played=True, status="Played"):
    return {
        "gameCode": game_code, "date": when, "played": played, "gameStatus": status,
        "local": {"club": {"name": home}, "score": h},
        "road": {"club": {"name": away}, "score": a},
    }


def leg(game_code, comp, home, away, market, outcome, spec, when):
    kickoff_ms = int(datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp() * 1000)
    return {"event_id": f"sr:match:{game_code}",
            "competition": comp, "home_team": home, "away_team": away,
            "market_id": market, "outcome_id": outcome, "specifier": spec,
            "kickoff_ms": kickoff_ms, "result": "pending"}


def test_european_parser_requires_explicit_completed_game_exact_score_and_identity():
    obj = official(10, "Virtus Bologna", "Zalgiris Kaunas", 74, 91, "2026-10-28T19:30:00Z")
    record = europe.parse_final(obj, "E", "E2026")
    assert record["home_score"] == 74 and record["away_score"] == 91
    assert record["source_event_id"] == "E2026:10"
    for change in (
        {"played": False}, {"gameStatus": "Scheduled"},
        {"gameCode": 0}, {"local": {"club": {"name": "Virtus Bologna"}, "score": "74"}},
        {"date": "2026-10-28T19:30:00"},
        {"road": {"club": {}, "score": 91}},
    ):
        assert europe.parse_final({**obj, **change}, "E", "E2026") is None


def test_european_match_requires_correct_league_orientation_date_and_unique_final():
    raw = official(6, "Hapoel IBI Tel Aviv", "Anadolu Efes Istanbul", 118, 88,
                   "2026-10-28T18:00:00Z")
    found = europe.parse_final(raw, "E", "E2026")
    selection = leg(900, "Euroleague", "Hapoel Tel-Aviv", "Anadolu Efes SK",
                    "219", "4", "", "2026-10-28T18:00:00Z")
    assert europe.match_final(selection, [found])["source_event_id"] == "E2026:6"
    assert europe.match_final({**selection, "competition": "Eurocup"}, [found]) is None
    assert europe.match_final({**selection, "home_team": "Anadolu Efes SK"}, [found]) is None
    assert europe.match_final({**selection, "kickoff_ms": selection["kickoff_ms"] + 5 * 3600000}, [found]) is None
    duplicate = europe.parse_final({**raw, "gameCode": 7}, "E", "E2026")
    assert europe.match_final(selection, [found, duplicate]) is None
    assert europe.match_final(selection, []) is None


def test_fixture_result_winner_and_overtime_totals_unchanged():
    event = {"source": europe.SOURCE, "source_event_id": "U2026:11",
             "home_score": 83, "away_score": 90}
    winner = leg(11, "Eurocup", "Le Mans Sarthe Basket", "Hapoel Jerusalem",
                 "219", "5", "", "2026-10-28T19:00:00Z")
    assert bs.settle_leg(winner, event)["result"] == "won"
    assert bs.settle_leg({**winner, "outcome_id": "4"}, event)["result"] == "lost"
    total = {**winner, "market_id": "225", "outcome_id": "12", "specifier": "total=158.5"}
    assert bs.settle_leg(total, event)["result"] == "won"
    assert bs.settle_leg({**total, "specifier": "total=173"}, event)["result"] == "void"
    assert bs.settle_leg({**total, "specifier": "total=invalid"}, event) == {**total}


def test_eight_leg_wzyhhv_research_example_settles_from_unique_official_european_finals(monkeypatch):
    # Scores are the archived public game results; this is synthetic ledger
    # data only and never writes to a real private booking database.
    fixtures = [
        ("E", 1, "Hapoel IBI Tel Aviv", "Anadolu Efes Istanbul", 118, 88,
         "Hapoel Tel-Aviv", "Anadolu Efes SK", "219", "4", ""),
        ("U", 2, "Aris Thessaloniki", "Cedevita Olimpija Ljubljana", 78, 73,
         "BC Aris Thessaloniki", "KK Cedevita Olimpija Ljubljana", "219", "4", ""),
        ("U", 3, "Slask Wroclaw", "Tofas Bursa", 74, 90,
         "Slask Wroclaw", "Tofas SK Bursa", "219", "5", ""),
        ("U", 4, "Neptunas Klaipeda", "Napoli Basket", 85, 94,
         "BC Neptunas Klaipeda", "Napoli Basket", "219", "5", ""),
        ("U", 5, "Le Mans Sarthe Basket", "Hapoel Jerusalem", 83, 90,
         "Le Mans Sarthe Basket", "Hapoel Jerusalem", "219", "5", ""),
        ("E", 6, "Virtus Segafredo Bologna", "Zalgiris Kaunas", 74, 91,
         "Virtus Bologna", "BC Zalgiris Kaunas", "225", "12", "total=158.5"),
        ("E", 7, "LDLC ASVEL Villeurbanne", "Partizan Belgrade", 82, 75,
         "ASVEL Lyon-Villeurbanne", "KK Partizan Belgrade", "225", "13", "total=178.5"),
        ("U", 8, "Derthona Basket", "Rostock Seawolves", 86, 83,
         "Derthona Basket", "Rostock Seawolves", "219", "4", ""),
    ]
    date_by_comp = {"E": "2026-10-28T18:00:00Z", "U": "2026-10-28T18:00:00Z"}
    pages = {"E": [], "U": []}
    selections = []
    for comp, i, name_h, name_a, h, a, home, away, mid, oid, spec in fixtures:
        pages[comp].append(official(i, name_h, name_a, h, a, date_by_comp[comp]))
        selections.append(leg(i, "Euroleague" if comp == "E" else "Eurocup",
                              home, away, mid, oid, spec, date_by_comp[comp]))
    writes = []
    ticket = {"fingerprint": "synthetic-wzyhhv", "status": "active",
              "last_checked_at": None, "legs": selections}
    monkeypatch.setattr(history, "list_recent", lambda limit: {"tickets": [ticket]})
    monkeypatch.setattr(history, "update_results",
                        lambda fp, updated, checked, status:
                        writes.append((fp, updated, status)))
    monkeypatch.setattr(bs, "_now", lambda: datetime(2026, 10, 29, 1, tzinfo=timezone.utc))

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return {"total": len(self.data), "data": self.data}

    def get(url, timeout=None, **kwargs):
        competition = url.split("/competitions/")[1][0]
        return FakeResponse(pages[competition])

    result = bs.settle_due(get=get, force=True)
    assert result["status"] == "success"
    assert result["verified_final_legs"] == 8
    assert result["nba_final_legs"] == 0
    assert result["tickets_updated"] == 1
    assert len(writes) == 1 and writes[0][2] == "won"
    assert [l["result"] for l in writes[0][1]] == ["won"] * 8
    assert {l["score_source"] for l in writes[0][1]} == {europe.SOURCE}


def test_provider_failure_is_not_a_zero_score_and_never_writes_fabricated_result(monkeypatch):
    selection = leg(90, "Euroleague", "Hapoel Tel-Aviv", "Anadolu Efes SK",
                    "219", "4", "", "2026-10-28T18:00:00Z")
    ticket = {"fingerprint": "safe", "status": "active",
              "last_checked_at": None, "legs": [selection]}
    writes = []
    monkeypatch.setattr(history, "list_recent", lambda limit: {"tickets": [ticket]})
    monkeypatch.setattr(history, "update_results", lambda *args: writes.append(args))
    monkeypatch.setattr(bs, "_now", lambda: datetime(2026, 10, 29, 1, tzinfo=timezone.utc))

    def unavailable(url, timeout=None, **kwargs):
        raise TimeoutError("upstream unavailable")

    result = bs.settle_due(get=unavailable, force=True)
    assert result["status"] == "SCORE_PROVIDER_PARTIAL"
    assert result["verified_final_legs"] == 0 and not writes
