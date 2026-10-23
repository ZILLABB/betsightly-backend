"""A complete SportyBet crawl must not be hidden by minor duplicate totals."""
import pytest

from leagues import sportybet as sb


def _meta(**changes):
    baseline = {
        "is_complete": False,
        "declared_total": 2025,
        "raw_fetched_records": 2026,
        "parsed_records": 2026,
        "unique_indexed_fixtures": 2024,
        "duplicates_removed": 2,
        "invalid_records": 0,
        "page_count": 21,
        "required_pages": 21,
        "error": "empty page 22 before declared total",
    }
    return {**baseline, **changes}


def test_live_shape_small_terminal_duplicate_gap_is_reconciled():
    result = sb._reconcile_terminal_duplicate_gap(_meta())
    assert result["is_complete"] is True
    assert result["provider_total_shortfall"] == 1
    assert result["error"] is None
    assert result["completion_basis"] == "terminal_empty_page_minor_duplicate_total_discrepancy"


@pytest.mark.parametrize("changes", [
    {"raw_fetched_records": 2024, "parsed_records": 2024, "duplicates_removed": 0},
    {"invalid_records": 1, "parsed_records": 2025},
    {"error": "TimeoutError: upstream timeout"},
    {"error": "empty page 21 before declared total"},
    {"error": "empty page 23 before declared total"},
    {"page_count": 20},
    {"unique_indexed_fixtures": 2017, "duplicates_removed": 9},
    {"declared_total": 3500, "required_pages": 35},
])
def test_incomplete_or_unsafe_crawls_still_rejected(changes):
    assert sb._reconcile_terminal_duplicate_gap(_meta(**changes))["is_complete"] is False


def test_exact_cached_board_can_be_read_after_a_safe_reconciliation(monkeypatch):
    from time import time
    fresh = time() - 60
    cache = {
        "fetched_at": fresh,
        "metadata": {**_meta(), "cache_schema_version": sb._CACHE_SCHEMA_VERSION},
        "fixtures": {"a|b": [{
            "event_id": "sr:match:1", "home_team": "A", "away_team": "B",
            "home_squad": "", "away_squad": "", "kickoff_ms": 1792782000000,
        }]},
    }
    monkeypatch.setattr(sb, "_db_get", lambda key: cache)
    snapshot = sb.cached_board_for_admin()
    assert snapshot is not None
    assert sb.board_metadata(snapshot)["is_complete"] is True
    assert sb.board_metadata(snapshot)["provider_total_shortfall"] == 1
    cache["fetched_at"] = time() - 11000
    assert sb.cached_board_for_admin() is None


def test_pagination_accepts_duplicate_boundary_only_with_verified_terminal(monkeypatch):
    def event(i):
        return {
            "eventId": f"sr:match:{i}",
            "homeTeamName": f"Home {i}",
            "awayTeamName": f"Away {i}",
            "estimateStartTime": 1792782000000,
            "markets": [],
        }
    pages = {
        1: [event(1), event(2), event(3)],
        2: [event(3), event(4), event(4)],
        3: [],
    }
    def get(url):
        page = int(url.split("pageNum=")[1])
        events = pages[page]
        return {"data": {
            "totalNum": 5,
            "tournaments": [{"name": "League", "events": events}] if events else [],
        }}
    monkeypatch.setattr(sb, "_get_json", get)
    monkeypatch.setattr(sb, "_db_get", lambda _: None)
    monkeypatch.setattr(sb, "_db_set", lambda *a, **kw: None)
    board = sb.fetch_board(force=True)
    meta = sb.board_metadata(board)
    assert meta["is_complete"] is True
    assert meta["provider_total_shortfall"] == 1
    assert meta["unique_indexed_fixtures"] == 4
