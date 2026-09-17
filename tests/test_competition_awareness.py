from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from leagues.base_rates import rates_for
from leagues.competition_registry import (
    COMPETITIONS, UNAVAILABLE_COMPETITIONS, regulation_score, tournament_context,
)
from leagues.elo_engine import probabilities_for_fixture
from leagues.fixture_ranker import builder_fixture_candidates
from leagues.picks import competition_evidence_allows_safe_tier
from leagues.predictor import predict
from leagues.results_checker import _evaluate_pick
from leagues.sportybet import MARKET_TO_SPORTYBET, _same_team, match_fixture
from leagues.team_history import HistoryIndex


def _team(team_id: str, name: str, side: str, score: str = "0", **extra):
    return {
        "homeAway": side, "score": score,
        "team": {"id": team_id, "uid": f"s:600~t:{team_id}", "displayName": name},
        **extra,
    }


def _scheduled_payload(slug="uefa.champions", name="UEFA Champions League"):
    return {
        "leagues": [{"slug": slug, "name": name}],
        "events": [{
            "id": "401", "date": "2026-09-20T19:00Z",
            "season": {"year": 2026, "type": 3, "slug": "quarterfinals"},
            "competitions": [{
                "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
                "competitors": [_team("1", "Alpha", "home"), _team("2", "Beta", "away")],
                "notes": [{"headline": "2nd Leg - Aggregate tied 1-1"}],
                "altGameNote": "UEFA Champions League, Quarterfinals",
                "venue": {"fullName": "National Stadium", "address": {"country": "England"}},
                "odds": [],
            }],
        }],
    }


def test_registry_is_unique_and_contains_verified_major_competitions():
    assert len(COMPETITIONS) == len(set(COMPETITIONS))
    for slug in (
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.nations",
        "fifa.world", "fifa.worldq.caf", "caf.nations", "caf.champions",
        "conmebol.libertadores", "afc.champions", "afc.cup",
    ):
        assert COMPETITIONS[slug].provider_verified
        assert COMPETITIONS[slug].enabled
    assert "ofc.nations" in UNAVAILABLE_COMPETITIONS
    assert "caf.super" in UNAVAILABLE_COMPETITIONS


def test_champions_league_ingestion_keeps_stage_leg_and_stable_team_ids(monkeypatch):
    from leagues import espn_source

    class Response:
        status_code = 200
        def json(self):
            return _scheduled_payload()

    monkeypatch.setattr(espn_source.requests, "get", lambda *a, **k: Response())
    fixtures = espn_source._fetch_league("uefa.champions", "20260920")
    assert len(fixtures) == 1
    fixture = fixtures[0]
    assert fixture["home"]["id"] == "1"
    assert fixture["competition_type"] == "CONTINENTAL_CLUB"
    assert fixture["stage"] == "Quarterfinals"
    assert fixture["leg_number"] == 2
    assert fixture["knockout"] is True
    assert fixture["competition"]["aggregate_score_before"] == {
        "home": 1, "away": 1, "source": "provider_note"}
    assert fixture["competition"]["qualification_state"] == "TIED"


@pytest.mark.parametrize("slug", ["uefa.europa", "uefa.europa.conf", "fifa.worldq.caf"])
def test_provider_supported_competitions_share_the_ingestion_path(monkeypatch, slug):
    from leagues import espn_source
    name = COMPETITIONS[slug].display_name

    class Response:
        status_code = 200
        def json(self):
            return _scheduled_payload(slug, name)

    monkeypatch.setattr(espn_source.requests, "get", lambda *a, **k: Response())
    fixture = espn_source._fetch_league(slug, "20260920")[0]
    assert fixture["league_slug"] == slug
    assert fixture["team_type"] == COMPETITIONS[slug].team_type


def test_tournament_context_infers_neutral_final_but_not_qualifier():
    final = tournament_context(
        "uefa.champions", {"season": {"slug": "final"}}, {"notes": []})
    qualifier = tournament_context(
        "fifa.worldq.caf", {"season": {"slug": "group-stage"}}, {"notes": []})
    assert final["neutral_venue"] is True
    assert final["knockout"] is True
    assert qualifier["neutral_venue"] is False
    assert qualifier["qualifier"] is True


def test_neutral_unpriced_fixture_does_not_receive_home_advantage():
    base = {
        "home_win": .50, "draw": .24, "away_win": .26,
        "avg_goals": 2.5, "over_1_5": .72, "over_2_5": .52, "btts": .50,
        "matches": 30, "base_rate_source": "competition",
    }
    fixture = {"odds": {}, "neutral_venue": True, "competition": {"knockout": True}}
    model = predict(fixture, base)
    assert model["probabilities"]["home_win"] == pytest.approx(
        model["probabilities"]["away_win"], abs=.0001)
    assert model["confidence_cap"] == .76


def test_international_ratings_are_separate_and_neutral_aware():
    ratings = {
        "__international__": {
            "Ghana": {"rating": 1600, "matches": 12},
            "Nigeria": {"rating": 1600, "matches": 12},
        },
        # Deliberately contradictory names in a club pool must be ignored.
        "fifa.world": {
            "Ghana": {"rating": 2000, "matches": 50},
            "Nigeria": {"rating": 1000, "matches": 50},
        },
    }
    fixture = {
        "league_slug": "fifa.world", "neutral_venue": True,
        "home": {"name": "Ghana"}, "away": {"name": "Nigeria"},
    }
    result = probabilities_for_fixture(fixture, ratings)
    assert result["rating_pool"] == "__international__"
    assert result["home_advantage_applied"] == 0
    assert result["home_win"] == result["away_win"]


def test_team_history_does_not_mix_club_and_national_identity():
    index = HistoryIndex({"matches": [
        {"date": "2026-01-01", "home": "Georgia", "away": "Armenia",
         "hs": 3, "as": 0, "team_type": "NATIONAL"},
        {"date": "2026-01-02", "home": "Georgia", "away": "Phoenix",
         "hs": 0, "as": 2, "team_type": "CLUB"},
    ]})
    assert index.team_form("Georgia", "home", "NATIONAL")["win_rate_5"] == 1
    assert index.team_form("Georgia", "home", "CLUB")["win_rate_5"] == 0


def test_club_trained_ml_does_not_claim_national_team_support(monkeypatch):
    from leagues import ml_models
    monkeypatch.setattr(ml_models, "_load", lambda: {
        "models": {"match_result": [("fake", object())]},
        "meta": {"supported_team_types": ["CLUB"]},
    })
    assert ml_models.predict_fixture({"team_type": "NATIONAL", "odds": {"implied": {"home_win": .5}}}, object()) is None


def test_thin_tournament_rate_shrinks_to_contextual_prior():
    direct = {
        "matches": 6, "avg_goals": 4.0, "over_1_5": .95, "over_2_5": .85,
        "home_win": .7, "draw": .1, "away_win": .2, "btts": .8,
        "home_goals": 2.4, "away_goals": 1.6,
    }
    prior = {
        "matches": 120, "avg_goals": 2.4, "over_1_5": .68, "over_2_5": .46,
        "home_win": .42, "draw": .28, "away_win": .30, "btts": .48,
        "home_goals": 1.3, "away_goals": 1.1,
    }
    cached = {
        "uefa.super_cup": direct,
        "_priors": {"region_type:Europe|CONTINENTAL_CLUB": prior},
    }
    result = rates_for("uefa.super_cup", cached)
    assert result["matches"] == 6
    assert result["avg_goals"] < 2.8
    assert result["base_rate_source"].endswith("region_type:Europe|CONTINENTAL_CLUB")


def test_regulation_score_excludes_extra_time_and_penalties():
    aet = {
        "status": {"type": {"name": "STATUS_FINAL_AET", "completed": True}},
        "competitors": [_team("1", "Spain", "home", "2", winner=True),
                        _team("2", "Germany", "away", "1", winner=False)],
        "details": [
            {"scoringPlay": True, "shootout": False, "scoreValue": 1,
             "team": {"id": "1"}, "clock": {"displayValue": "51'"}},
            {"scoringPlay": True, "shootout": False, "scoreValue": 1,
             "team": {"id": "2"}, "clock": {"displayValue": "89'"}},
            {"scoringPlay": True, "shootout": False, "scoreValue": 1,
             "team": {"id": "1"}, "clock": {"displayValue": "119'"}},
        ],
    }
    score = regulation_score(aet)
    assert score["score_90"] == {"home": 1, "away": 1}
    assert score["score_extra_time"] == {"home": 1, "away": 0}
    assert _evaluate_pick({"market": "draw"}, score["home_score"], score["away_score"]) == "won"

    pens = {
        "status": {"type": {"name": "STATUS_FINAL_PEN", "completed": True}},
        "competitors": [_team("1", "Portugal", "home", "0", shootoutScore="3"),
                        _team("2", "France", "away", "0", shootoutScore="5", winner=True)],
        "details": [{"scoringPlay": True, "shootout": True, "team": {"id": "2"},
                     "clock": {"displayValue": "120'"}}],
    }
    score = regulation_score(pens)
    assert score["score_90"] == {"home": 0, "away": 0}
    assert score["penalty_score"] == {"home": 3, "away": 5}
    assert _evaluate_pick({"market": "away_win"}, 0, 0) == "lost"


def test_sportybet_tournament_alias_and_national_collision_guards():
    kickoff = "2026-09-20T19:00:00Z"
    kickoff_ms = int(datetime.fromisoformat(kickoff.replace("Z", "+00:00")).timestamp() * 1000)
    entry = {
        "home": "Ghana", "away": "Nigeria", "home_squad": "", "away_squad": "",
        "kickoff_ms": kickoff_ms, "competition": "AFCON", "event_id": "sb-1", "prices": {},
    }
    result = match_fixture({"ghana|nigeria": [entry]}, "Ghana", "Nigeria", kickoff,
                           "Africa Cup of Nations")
    assert result["status"] == "MATCHED"
    assert _same_team("guinea", "equatorial guinea") is False


def test_qualification_outcomes_are_not_mapped_to_regulation_win_markets():
    assert "home_to_qualify" not in MARKET_TO_SPORTYBET
    assert "away_to_qualify" not in MARKET_TO_SPORTYBET


def test_builder_accepts_trusted_tournament_candidate_and_keeps_fixture_identity():
    fixture = {
        "league": "UEFA Champions League", "league_slug": "uefa.champions",
        "competition_type": "CONTINENTAL_CLUB", "commence_time": "2026-09-20T19:00:00Z",
        "home": {"name": "Alpha"}, "away": {"name": "Beta"},
    }
    pick = {
        "match_id": "ucl-1", "market": "over_1_5", "market_group": "goals",
        "confidence": .82, "odds": 1.35, "odds_are_real": True,
        "expected_value": .02, "bookable": True, "_fixture": fixture,
        "trust": {"evidence_state": "SUPPORTED", "evidence_strength": .9,
                  "evidence_adjusted_probability": .79, "lower_reliability_bound": .72},
    }
    selected = builder_fixture_candidates([pick])
    assert len(selected) == 1
    assert selected[0]["match_id"] == "ucl-1"
    assert selected[0]["public_rank"] == 1


def test_thin_tournament_is_not_safe_tier_eligible():
    assert not competition_evidence_allows_safe_tier({
        "competition_type": "INTERNATIONAL_TOURNAMENT",
        "competition_historical_sample": 6,
    })
    assert competition_evidence_allows_safe_tier({
        "competition_type": "INTERNATIONAL_TOURNAMENT",
        "competition_historical_sample": 30,
    })


def test_published_results_retain_competition_metadata():
    from leagues.picks_db import archive_slip, ensure_table, get_history

    ensure_table()
    game = {
        "match_id": "meta-fixture", "home_team": "Ghana", "away_team": "Nigeria",
        "league": "Africa Cup of Nations", "league_slug": "caf.nations",
        "competition_type": "INTERNATIONAL_TOURNAMENT", "competition_region": "Africa",
        "team_type": "NATIONAL", "competition_stage": "Quarterfinals",
        "competition_context_label": "Quarterfinals", "neutral_venue": True,
        "knockout": True, "leg_number": None, "base_rate_source": "competition+team_type:NATIONAL",
        "competition_historical_sample": 52, "kickoff": "2099-01-01T18:00:00Z",
        "prediction": "Over 1.5 Goals", "market": "over_1_5",
        "prediction_type": "goals", "odds": 1.3, "confidence": .8,
    }
    assert archive_slip("2099-01-01", "competition_meta", [game], 1.3, .8)
    saved = next(row for row in get_history(30000, "competition_meta")
                 if row["date"] == "2099-01-01")["picks"][0]
    assert saved["league_slug"] == "caf.nations"
    assert saved["competition_type"] == "INTERNATIONAL_TOURNAMENT"
    assert saved["neutral_venue"] is True


def test_competition_coverage_exposes_provider_failure(monkeypatch):
    from leagues import base_rates, elo_engine, engine, espn_source
    from leagues.api import competition_coverage

    monkeypatch.setattr(engine, "run_pipeline", lambda **kwargs: ([], []))
    monkeypatch.setattr(base_rates, "get_base_rates", lambda: {})
    monkeypatch.setattr(elo_engine, "get_ratings", lambda: {})
    monkeypatch.setattr(espn_source, "fetch_health", lambda: {
        "uefa.champions": {"provider_active": False, "error": "timeout"}
    })
    result = asyncio.run(competition_coverage())
    row = next(item for item in result["competitions"] if item["slug"] == "uefa.champions")
    assert row["configured"] is True
    assert row["provider_active"] is False
    assert row["error"] == "timeout"
    assert any(item["slug"] == "ofc.nations" and not item["configured"]
               for item in result["competitions"])
