from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from leagues import ticket_history as history

def result(games=None, status="success"):
    return {"status": status, "request_id": "request-1", "odds": 3.2, "board": {"board_snapshot_id":"board-1"}, "booking": {"readback_validation":"PASSED"}, "games": games if games is not None else [{"fixture_id":"f1","selection_id":"s1","home_team":"A","away_team":"B","league":"L","market":"over_1_5","prediction":"Over 1.5","odds":1.5,"confidence":.7,"evidence_adjusted_probability":.69,"trust":{"grade":"B"},"kickoff":"2099-01-01T12:00:00Z"}]}

def setup_db(monkeypatch):
    db=create_engine("sqlite://",poolclass=StaticPool,connect_args={"check_same_thread":False}); monkeypatch.setattr(history,"engine",db); history.ensure_tables(); return db

def test_anonymous_history_is_atomic_and_idempotent(monkeypatch):
    db=setup_db(monkeypatch); payload={"anonymous_id":"anon_123456789012345","mode":"target_odds","horizon":"today","target_odds":2}
    first=history.record_generated_ticket(payload,result()); second=history.record_generated_ticket(payload,result())
    assert first==second
    with db.connect() as c:
        assert len(c.execute(select(history.ticket_history)).all())==1
        selection=c.execute(select(history.ticket_selections)).mappings().one()
    assert selection["fixture_id"]=="f1" and selection["market"]=="over_1_5" and selection["kickoff"] is not None

def test_fingerprint_is_order_independent_and_identity_scoped(monkeypatch):
    db=setup_db(monkeypatch); games=result()["games"]+[dict(result()["games"][0],fixture_id="f2",selection_id="s2")]
    assert history._fingerprint(games)==history._fingerprint(list(reversed(games)))
    assert history.record_generated_ticket({"anonymous_id":"anon_AAAAAAAAAAAAA","mode":"strongest","horizon":"today"},result(games))
    assert history.record_generated_ticket({"anonymous_id":"anon_BBBBBBBBBBBBB","mode":"strongest","horizon":"today"},result(games))
    assert history.record_generated_ticket({"anonymous_id":"anon_AAAAAAAAAAAAA","mode":"strongest","horizon":"today"},result([games[0]]))
    with db.connect() as c: assert len(c.execute(select(history.ticket_history)).all())==3

def test_invalid_or_identity_free_results_do_not_persist(monkeypatch):
    db=setup_db(monkeypatch); payload={"mode":"target_odds","horizon":"today"}
    for response in (result(status="unavailable"),result(status="board_refreshing"),result([]),result(status="error")):
        assert history.record_generated_ticket(payload,response) is None
    with db.connect() as c: assert len(c.execute(select(history.ticket_history)).all())==0

def test_builder_identity_is_excluded_from_engine_but_kept_for_history():
    from leagues import api

    request = api.BuilderV2Request(
        mode="target_odds",
        target_odds=2,
        horizon="today",
        anonymous_id="anon_123456789012345",
    )

    engine_payload = api._builder_v2_payload(request)
    persistence_payload = api._builder_v2_persistence_payload(
        request,
        engine_payload,
    )

    assert "anonymous_id" not in engine_payload
    assert persistence_payload["anonymous_id"] == "anon_123456789012345"
    assert persistence_payload["target_odds"] == 2
    assert persistence_payload["mode"] == "target_odds"



def test_recent_exposure_reads_only_current_anonymous_user(monkeypatch):
    db = setup_db(monkeypatch)

    anon_a = "anon_AAAAAAAAAAAAA"
    anon_b = "anon_BBBBBBBBBBBBB"

    first = result()
    second_game = dict(
        result()["games"][0],
        fixture_id="f2",
        selection_id="s2",
        home_team="C",
        away_team="D",
        league="L2",
        market="over_2_5",
    )

    history.record_generated_ticket(
        {
            "anonymous_id": anon_a,
            "mode": "strongest",
            "horizon": "today",
        },
        first,
    )

    history.record_generated_ticket(
        {
            "anonymous_id": anon_a,
            "mode": "strongest",
            "horizon": "today",
        },
        result([second_game]),
    )

    history.record_generated_ticket(
        {
            "anonymous_id": anon_b,
            "mode": "strongest",
            "horizon": "today",
        },
        result([
            dict(
                second_game,
                fixture_id="other-user",
                selection_id="other-selection",
            )
        ]),
    )

    exposure = history.recent_exposure(anon_a)

    assert exposure["history_ticket_count"] == 2
    assert set(exposure["exact_selection_ids"]) == {"s1", "s2"}
    assert set(exposure["recent_fixture_ids"]) == {"f1", "f2"}
    assert "other-selection" not in exposure["exact_selection_ids"]


def test_build_another_is_not_an_optimizer_identity_input():
    from leagues import api

    request = api.BuilderV2Request(
        mode="target_odds",
        target_odds=2,
        horizon="today",
        anonymous_id="anon_123456789012345",
        build_another=True,
    )

    engine_payload = api._builder_v2_payload(request)
    persistence_payload = api._builder_v2_persistence_payload(
        request,
        engine_payload,
    )

    assert "anonymous_id" not in engine_payload
    assert "build_another" not in engine_payload

    assert persistence_payload["anonymous_id"] == "anon_123456789012345"
    assert persistence_payload["build_another"] is True
