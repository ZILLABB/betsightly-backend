"""Regression tests for bookmaker -> verified-score provider settlement identity.

20 October 2026 exposed exact-name mismatches even when ESPN had an
authoritatively completed fixture. These tests must never need live APIs.
"""
from datetime import datetime, timezone

from leagues.editorial_settlement import grade_manual_slip
from leagues.results_checker import _index_free_finals, _lookup_settlement_score, _normalize_name


def _manual(home: str, away: str, market: str = "home_win") -> dict:
    return {
        "home_team": home,
        "away_team": away,
        "market": market,
        "prediction": "Home Win",
        "kickoff": "2026-10-20T19:00:00+00:00",
        "editorial_manual": True,
    }


def _espn(home: str, away: str, home_score: int = 2, away_score: int = 1) -> dict:
    return {
        "home": home,
        "away": away,
        "date": "2026-10-20",
        "home_score": home_score,
        "away_score": away_score,
        "completed": True,
        "provider": "espn",
        "provider_event_id": "espn-confirmed-20261020",
        "score_90": {"home": home_score, "away": away_score},
        "match_status": "FT",
    }


def test_oct20_verified_bookmaker_names_match_completed_espn_names():
    variants = [
        ("Man City", "Manchester City"),
        ("Roma", "AS Roma"),
        ("Wolves", "Wolverhampton Wanderers"),
        ("Huddersfield", "Huddersfield Town"),
        ("Luton", "Luton Town"),
        ("Leicester", "Leicester City"),
        ("Sabah Masazir", "Sabah FK"),
        ("Fenerbahce Istanbul", "Fenerbahce"),
        ("PSG", "Paris Saint-Germain"),
        ("Stuttgart", "VfB Stuttgart"),
        ("Bodoe/Glimt", "Bodo/Glimt"),
        ("Al Nassr Club", "Al Nassr"),
        ("Al-Ittihad Club", "Al Ittihad"),
    ]
    for manual, provider in variants:
        assert _normalize_name(manual) == _normalize_name(provider), (
            manual, provider,
        )


def test_verified_espn_score_now_settles_manual_slip_with_alias():
    record = {
        "date": "2026-10-20",
        "tier": "5_odds",
        "games": [_manual("Roma", "Slovan Bratislava")],
    }
    scores = _index_free_finals([_espn("AS Roma", "Slovan Bratislava", 4, 0)])
    result = grade_manual_slip(
        record, scores, now=datetime(2026, 10, 20, 23, tzinfo=timezone.utc),
    )
    assert result["result_status"] == "won"
    assert result["games"][0]["status"] == "won"
    assert result["games"][0]["settlement_evidence"]["provider"] == "espn"


def test_name_variants_do_not_match_other_teams_or_dates():
    scores = _index_free_finals([
        _espn("Manchester City", "AEK Athens"),
    ])
    assert _lookup_settlement_score(scores, "Man City", "AEK Athens", "2026-10-20")
    assert _lookup_settlement_score(
        scores, "Man City Women", "AEK Athens", "2026-10-20",
    ) is None
    assert _lookup_settlement_score(
        scores, "Man City", "AEK Athens", "2026-10-21",
    ) is None
    assert _lookup_settlement_score(
        scores, "Man City", "Villarreal", "2026-10-20",
    ) is None


def test_independent_football_data_provider_fills_missing_espn_final(monkeypatch):
    """A verified second provider is used rather than inventing an ESPN score."""
    import leagues.results_checker as checker
    from services import verified_incident_finals, openligadb_score_source
    from services import free_football_score_sources

    monkeypatch.setattr(checker, "_collect_espn_scores_ranged", lambda *a, **kw: {})
    monkeypatch.setattr(verified_incident_finals, "incident_finals", lambda p: [])
    monkeypatch.setattr(openligadb_score_source, "openligadb_finals", lambda p: [])
    monkeypatch.setattr(free_football_score_sources, "football_data_finals",
                        lambda start, end: [_espn("Manchester City", "AEK Athens") | {
                            "provider": "football-data.org",
                        }])
    monkeypatch.setattr(free_football_score_sources, "sportsdb_finals", lambda p: [])
    monkeypatch.setattr(checker, "_get_odds_api_key", lambda: None)

    scores, source = checker._collect_scores_for_picks(
        [_manual("Man City", "AEK Athens")], allow_fallback=True,
    )
    final = _lookup_settlement_score(
        scores, "Man City", "AEK Athens", "2026-10-20",
    )
    assert final is not None
    assert final["provider"] == "football-data.org"
    assert final["score_90"] == {"home": 2, "away": 1}
    assert "football-data.org" in source
