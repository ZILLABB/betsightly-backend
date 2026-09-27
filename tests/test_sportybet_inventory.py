from leagues import sportybet
from leagues import sportybet_inventory


def _board():
    return {
        "__meta__": {
            "snapshot_id": "snap-123",
            "declared_total": 1,
            "page_count": 1,
            "required_pages": 1,
            "is_complete": True,
            "fetched_at": 1_700_000_000.0,
            "error": None,
        },
        "alpha|beta": [{
            "event_id": "evt-1",
            "competition": "Test League",
            "home_team": "Alpha FC",
            "away_team": "Beta FC",
            "home_squad": "",
            "away_squad": "",
            "kickoff_ms": 1_700_003_600_000,
            "prices": {
                "over_1_5": 1.42,
                "home_or_draw": 1.20,
            },
            "margins": {
                "over_1_5": 0.05,
                "home_or_draw": 0.04,
            },
            "market_refs": {
                "18|total=1.5": {
                    "market_id": "18",
                    "specifier": "total=1.5",
                    "outcomes": {
                        "12": {
                            "outcome_id": "12",
                            "active": True,
                            "odds": 1.42,
                        },
                    },
                },
                "10|": {
                    "market_id": "10",
                    "specifier": "",
                    "outcomes": {
                        "9": {
                            "outcome_id": "9",
                            "active": True,
                            "odds": 1.20,
                        },
                    },
                },
            },
        }],
    }


def test_normalize_board_is_compact_shadow_only():
    result = sportybet_inventory.normalize_board(_board())

    assert result["status"] == "success"
    assert result["source"] == "SPORTYBET_FIRST_SHADOW_BOARD"
    assert result["shadow_only"] is True
    assert result["can_publish"] is False
    assert result["can_book"] is False
    assert result["authoritative_for_user_output"] is False
    assert result["snapshot_id"] == "snap-123"
    assert result["complete"] is True
    assert result["fixture_count"] == 1
    assert result["selection_count"] == 2

    fixture = result["fixtures"][0]
    assert fixture["sportybet_event_id"] == "evt-1"
    assert fixture["home_team"] == "Alpha FC"
    assert fixture["away_team"] == "Beta FC"
    assert set(fixture["supported_markets"]) == {
        "over_1_5",
        "home_or_draw",
    }
    assert "market_refs" not in fixture
    assert "prices" not in fixture


def test_suspended_outcome_is_not_exposed_as_available():
    board = _board()
    board["alpha|beta"][0]["market_refs"]["18|total=1.5"]["outcomes"]["12"]["active"] = False

    result = sportybet_inventory.normalize_board(board)
    fixture = result["fixtures"][0]

    assert "over_1_5" not in fixture["supported_markets"]
    assert result["selection_count"] == 1


def test_cached_inventory_never_fetches_network(monkeypatch):
    board = _board()
    monkeypatch.setattr(
        sportybet,
        "_db_get",
        lambda key: {
            "fixtures": {
                key: value
                for key, value in board.items()
                if key != "__meta__"
            },
            "metadata": board["__meta__"],
        },
    )
    monkeypatch.setattr(
        sportybet,
        "_get_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("network fetch must not happen")
        ),
    )

    result = sportybet_inventory.cached_shadow_inventory()

    assert result["status"] == "success"
    assert result["fixture_count"] == 1
    assert result["refresh_required"] is False


def test_empty_cache_fails_closed_without_refresh(monkeypatch):
    monkeypatch.setattr(sportybet, "_db_get", lambda key: None)
    monkeypatch.setattr(
        sportybet,
        "_get_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("network fetch must not happen")
        ),
    )

    result = sportybet_inventory.cached_shadow_inventory()

    assert result["status"] == "unavailable"
    assert result["reason"] == "sportybet_cache_empty"
    assert result["refresh_required"] is True
    assert result["fixtures"] == []


def test_status_does_not_return_fixture_payload(monkeypatch):
    monkeypatch.setattr(
        sportybet_inventory,
        "cached_shadow_inventory",
        lambda: {
            "status": "success",
            "source": "SPORTYBET_FIRST_SHADOW_BOARD",
            "provider": "sportybet",
            "shadow_only": True,
            "can_publish": False,
            "can_book": False,
            "authoritative_for_user_output": False,
            "refresh_required": False,
            "snapshot_id": "snap",
            "complete": True,
            "fixture_count": 1200,
            "selection_count": 8000,
            "competition_count": 230,
            "fixtures": [{"secret": "do-not-return"}],
        },
    )

    result = sportybet_inventory.status()

    assert result["fixture_count"] == 1200
    assert "fixtures" not in result
