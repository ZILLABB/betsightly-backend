from leagues import builder_editor


def _pick(selection, fixture, odds=1.4, probability=.75):
    return {
        "selection_id": selection, "match_id": fixture, "market": "over_1_5",
        "market_group": "goals_over_1_5", "odds": odds,
        "confidence": probability, "selection_probability": probability,
        "quality_score": probability * 100, "bookable": True,
        "_fixture": {
            "home": {"name": f"{fixture}-home"},
            "away": {"name": f"{fixture}-away"},
        },
    }


def _game(selection, fixture, odds=1.4):
    return {"selection_id": selection, "match_id": fixture,
            "fixture_id": fixture, "odds": odds}


def test_local_replace_is_different_fixture_one_for_one_and_preserves_others(
        monkeypatch):
    before = {
        "games": [_game("a", "fixture-a"), _game("b", "fixture-b")],
        "odds": 2.0,
    }
    pool = [
        _pick("a", "fixture-a"), _pick("a-alt", "fixture-a", 1.6, .8),
        _pick("b", "fixture-b"), _pick("c", "fixture-c", 1.5, .79),
    ]
    calls = []

    def build(target, **kwargs):
        calls.append(kwargs)
        picks = kwargs["pool"]
        return {
            "ok": True, "picks": picks, "odds": 2.1, "legs": 2,
            "hit_probability": .55, "expected_return": 1.15,
        }

    monkeypatch.setattr(builder_editor, "build_slip", build)
    monkeypatch.setattr(
        builder_editor, "_public_result_from_build",
        lambda target, horizon, built, board, timings, force_booking=False: {
            "status": "success", "odds": built["odds"],
            "games": [_game(p["selection_id"], p["match_id"], p["odds"])
                      for p in built["picks"]],
            "booking": {"status": "active", "share_code": "NEW",
                        "readback_validation": "PASSED"},
        },
    )
    result, replacement = builder_editor._replace_fixture_locally(
        before=before, current=before["games"][0], candidates=pool,
        target=2, horizon="week", board={}, locked={"b"},
        excluded_fixtures=set(), excluded_selections=set(), timings={},
    )
    assert replacement == "c"
    assert [game["selection_id"] for game in result["games"]] == ["c", "b"]
    assert len(result["games"]) == len(before["games"])
    assert calls[0]["locked_selection_ids"] == {"b"}
    assert calls[0]["excluded_fixture_ids"] == {"fixture-a"}
    assert {pick["match_id"] for pick in calls[0]["pool"]} == {
        "fixture-b", "fixture-c",
    }


def test_local_replace_fails_safely_if_only_same_fixture_market_exists(
        monkeypatch):
    before = {"games": [_game("a", "fixture-a")], "odds": 1.4}
    result, replacement = builder_editor._replace_fixture_locally(
        before=before, current=before["games"][0],
        candidates=[_pick("a", "fixture-a"),
                    _pick("a-alt", "fixture-a", 1.6, .8)],
        target=1.4, horizon="week", board={}, locked=set(),
        excluded_fixtures=set(), excluded_selections=set(), timings={},
    )
    assert result is None and replacement is None


def test_local_replace_withholds_unverified_booking(monkeypatch):
    before = {"games": [_game("a", "fixture-a")], "odds": 1.4}
    replacement = _pick("c", "fixture-c")
    monkeypatch.setattr(builder_editor, "build_slip", lambda *args, **kwargs: {
        "ok": True, "picks": [replacement], "odds": 1.4, "legs": 1,
        "hit_probability": .7, "expected_return": .98,
    })
    monkeypatch.setattr(
        builder_editor, "_public_result_from_build",
        lambda *args, **kwargs: {
            "status": "success", "games": [_game("c", "fixture-c")],
            "booking": {"status": "active", "share_code": "BAD",
                        "readback_validation": "FAILED"},
        },
    )
    result, selected = builder_editor._replace_fixture_locally(
        before=before, current=before["games"][0],
        candidates=[_pick("a", "fixture-a"), replacement],
        target=1.4, horizon="week", board={}, locked=set(),
        excluded_fixtures=set(), excluded_selections=set(), timings={},
    )
    assert result is None and selected is None
