from copy import deepcopy
from datetime import (
    datetime,
    timezone,
)

import pytest

from leagues import sportybet_shadow


def _entry():
    kickoff = datetime(
        2026,
        9,
        30,
        18,
        tzinfo=timezone.utc,
    )

    return {
        "event_id": "9001",
        "home_team": "Man Utd",
        "away_team": "Chelsea",
        "home_squad": "",
        "away_squad": "",
        "kickoff_ms": int(
            kickoff.timestamp()
            * 1000
        ),
        "competition": "Premier League",
        "prices": {
            "over_1_5": 1.40,
        },
        "margins": {
            "over_1_5": .05,
        },
        "market_refs": {
            "18|total=1.5": {
                "market_id": "18",
                "specifier": "total=1.5",
                "outcomes": {},
            },
        },
    }


def _sample():
    return {
        "event_id": "9001",
        "league_slug": "eng.1",
        "league": "Premier League",
        "readiness": "READY_FOR_SHADOW_MODEL",
        "home_history": {
            "status": "MATCHED",
            "team": "Manchester United",
            "matches": 8,
        },
        "away_history": {
            "status": "MATCHED",
            "team": "Chelsea",
            "matches": 9,
        },
    }


def _board():
    return {
        "__meta__": {
            "snapshot_id": "sb-shadow-1",
            "is_complete": True,
        },
        "man utd|chelsea": [
            _entry()
        ],
    }


def test_shadow_fixture_uses_espn_identity_but_not_sportybet_implied_probability():
    fixture = sportybet_shadow._shadow_fixture(
        _sample(),
        _entry(),
        {
            "snapshot_id": "sb-shadow-1",
        },
    )

    assert fixture is not None

    assert (
        fixture["home"]["name"]
        == "Manchester United"
    )

    assert (
        fixture["away"]["name"]
        == "Chelsea"
    )

    assert fixture["league_slug"] == "eng.1"

    assert (
        fixture["odds"]["provider"]
        == "SportyBet"
    )

    assert (
        fixture["odds"]["over_1_5"]
        == 1.40
    )

    assert "implied" not in fixture["odds"]
    assert "implied_over" not in fixture["odds"]
    assert "implied_under" not in fixture["odds"]

    assert (
        fixture["_sportybet_match"]["status"]
        == "MATCHED"
    )

    assert (
        fixture["_shadow_supplemental"]
        is True
    )


def test_shadow_evaluation_never_mutates_live_pool(monkeypatch):
    live_picks = [{
        "match_id": "live-1",
        "market": "over_1_5",
        "confidence": .75,
    }]

    original = deepcopy(
        live_picks
    )

    captured = {}

    monkeypatch.setattr(
        sportybet_shadow,
        "rates_for",
        lambda slug, cached: {
            "matches": 30,
            "home_win": .45,
            "draw": .27,
            "away_win": .28,
            "avg_goals": 2.6,
            "over_1_5": .74,
            "over_2_5": .53,
            "btts": .51,
            "base_rate_source": "competition+global",
        },
    )

    monkeypatch.setattr(
        sportybet_shadow,
        "probabilities_for_fixture",
        lambda fixture, ratings: None,
    )

    def fake_predict(
        fixture,
        base,
        elo,
    ):
        captured[
            "had_implied"
        ] = "implied" in (
            fixture.get("odds")
            or {}
        )

        return {
            "probabilities": {
                "over_1_5": .76,
            },
            "expected_goals": {
                "home": 1.4,
                "away": 1.1,
                "total": 2.5,
                "source": "league_base",
            },
            "has_market": False,
            "elo_agreement": None,
            "confidence_cap": .80,
            "competition_context": (
                fixture.get("competition")
                or {}
            ),
            "base_rate_source": (
                base.get(
                    "base_rate_source"
                )
            ),
        }

    monkeypatch.setattr(
        sportybet_shadow,
        "predict",
        fake_predict,
    )

    def fake_build(
        fixture,
        model,
        min_confidence,
        fit,
    ):
        return [{
            "match_id": fixture[
                "match_id"
            ],
            "market": "over_1_5",
            "confidence": .76,
            "odds": 1.40,
            "odds_are_real": True,
            "bookable": True,
            "market_floor_eligible": True,
            "_fixture": fixture,
            "_model": model,
        }]

    monkeypatch.setattr(
        sportybet_shadow,
        "build_picks",
        fake_build,
    )

    def fake_rank(
        picks,
        include_all_eligible=True,
    ):
        result = []

        for pick in picks:
            copied = dict(
                pick
            )

            copied.update({
                "selection_probability": (
                    copied.get(
                        "confidence"
                    )
                ),
                "quality_score": 80.0,
                "market_trust_state": "TRUSTED",
            })

            result.append(
                copied
            )

        return result

    monkeypatch.setattr(
        sportybet_shadow,
        "canonical_fixture_recommendations",
        fake_rank,
    )

    report = (
        sportybet_shadow.evaluate_shadow_supplemental(
            {
                "samples": [
                    _sample()
                ]
            },
            _board(),
            cached_rates={},
            history=None,
            ratings={},
            fit={
                "n": 0,
                "groups": {},
            },
            live_picks=live_picks,
        )
    )

    assert captured["had_implied"] is False

    assert (
        report[
            "sportybet_used_as_probability_anchor"
        ]
        is False
    )

    assert (
        report[
            "sportybet_used_as_price_source"
        ]
        is True
    )

    assert report["modelled_fixture_count"] == 1

    assert (
        report["ranked_shadow_candidate_count"]
        == 1
    )

    assert (
        report["bookable_shadow_candidate_count"]
        == 1
    )

    assert (
        report["prediction_pool_changed"]
        is False
    )

    assert (
        report["official_record_changed"]
        is False
    )

    assert live_picks == original


def test_shadow_fixture_rejects_competition_context_we_cannot_reconstruct():
    sample = _sample()

    sample.update({
        "league_slug": "eng.fa",
        "league": "FA Cup",
    })

    assert (
        sportybet_shadow._shadow_fixture(
            sample,
            _entry(),
            {
                "snapshot_id": "sb-shadow-1",
            },
        )
        is None
    )
