from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select

from leagues import football_first_shadow_observations as obs


class _History:
    pass


def _fixture(slug="eng.1", event_id="fixture-1", kickoff=None):
    kickoff = kickoff or (datetime.now(timezone.utc) + timedelta(hours=5))
    return {
        "event_id": event_id,
        "league_slug": slug,
        "league": "Premier League",
        "commence_time": kickoff.isoformat(),
        "home": {"name": "Home"},
        "away": {"name": "Away"},
    }


def _champion(home=.50, draw=.25, away=.25):
    return {
        "probabilities": {
            "home_win": home,
            "draw": draw,
            "away_win": away,
        }
    }


def _challenger(home=.55, draw=.25, away=.20):
    return {
        "status": "READY",
        "model_version": "shadow-v1",
        "feature_version": "football-first-runtime-core-v1",
        "probabilities": {
            "home_win": home,
            "draw": draw,
            "away_win": away,
        },
        "feature_evidence": {
            "home_history": 8,
            "away_history": 7,
        },
    }


def test_allowlist_is_explicit_and_mixed_leagues_fail_closed():
    assert len(obs.ROBUST_MATCH_RESULT_LEAGUES) == 29
    assert obs.ROBUST_MATCH_RESULT_LEAGUES["eng.1"] == 39
    assert obs.ROBUST_MATCH_RESULT_LEAGUES["chn.1"] == 169
    assert obs.ROBUST_MATCH_RESULT_LEAGUES["gre.1"] == 197

    allowed, _, reason = obs.allowed_fixture(_fixture("ger.2"))
    assert allowed is False
    assert reason == "mixed_offline_evidence"


def test_observation_requires_pre_kickoff_and_stable_fixture_id():
    now = datetime.now(timezone.utc)
    row, reason = obs.build_observation(
        _fixture(kickoff=now - timedelta(minutes=1)),
        _champion(),
        _challenger(),
        observed_at=now,
    )
    assert row is None
    assert reason == "fixture_started"

    fixture = _fixture()
    fixture["event_id"] = None
    row, reason = obs.build_observation(
        fixture,
        _champion(),
        _challenger(),
        observed_at=now,
    )
    assert row is None
    assert reason == "missing_fixture_id"


def test_first_write_wins_and_never_rewrites_probabilities(monkeypatch):
    db = create_engine("sqlite:///:memory:")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("FOOTBALL_FIRST_SHADOW_ENABLED", "true")
    monkeypatch.setattr(
        obs.shadow,
        "predict_fixture",
        lambda fixture, history: _challenger(home=.55, draw=.25, away=.20),
    )

    fixture = _fixture()
    first = obs.observe_fixture(
        fixture,
        _champion(home=.50, draw=.25, away=.25),
        _History(),
        db_engine=db,
    )
    assert first["status"] == "RECORDED"

    monkeypatch.setattr(
        obs.shadow,
        "predict_fixture",
        lambda fixture, history: _challenger(home=.90, draw=.05, away=.05),
    )
    second = obs.observe_fixture(
        fixture,
        _champion(home=.90, draw=.05, away=.05),
        _History(),
        db_engine=db,
    )
    assert second["status"] == "EXISTS"

    with db.begin() as conn:
        stored = conn.execute(select(obs.observations)).mappings().one()

    assert stored["champion_home"] == .50
    assert stored["challenger_home"] == .55


def test_production_requires_second_explicit_override(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FOOTBALL_FIRST_SHADOW_ENABLED", "true")
    monkeypatch.delenv(obs.PRODUCTION_OVERRIDE_FLAG, raising=False)
    allowed, reason = obs.collection_allowed()
    assert allowed is False
    assert reason == "production_override_disabled"


def test_report_cannot_auto_promote_small_sample(monkeypatch):
    db = create_engine("sqlite:///:memory:")
    obs.ensure_table(db)
    monkeypatch.setattr(
        obs.shadow,
        "status",
        lambda: {"model_version": "shadow-v1", "shadow_only": True},
    )
    monkeypatch.setattr(obs, "collection_allowed", lambda: (True, "enabled"))

    now = datetime.now(timezone.utc)
    with db.begin() as conn:
        for index in range(20):
            outcome = index % 3
            conn.execute(
                obs.observations.insert().values(
                    observation_id=f"id-{index}",
                    observation_key=f"key-{index}",
                    model_version="shadow-v1",
                    feature_version="football-first-runtime-core-v1",
                    target="match_result",
                    fixture_id=f"fx-{index}",
                    league_slug="eng.1",
                    api_league_id=39,
                    competition="Premier League",
                    home_team="Home",
                    away_team="Away",
                    kickoff=now - timedelta(days=1),
                    observed_at=now - timedelta(days=2),
                    champion_away=.25,
                    champion_draw=.25,
                    champion_home=.50,
                    challenger_away=.20,
                    challenger_draw=.25,
                    challenger_home=.55,
                    status="settled",
                    settled_at=now,
                    home_score=1,
                    away_score=0,
                    outcome_class=outcome,
                    settlement_source="test",
                )
            )

    report = obs.shadow_report(db_engine=db)
    assert report["comparison"]["n"] == 20
    assert report["comparison"]["status"] != "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert report["automatic_promotion"] is False
    assert report["live_adjustment_allowed"] is False
