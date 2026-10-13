"""Contract tests for manual desk market aliases and code import safety."""
from unittest.mock import patch
import pytest
from leagues import editorial_manual as M
from leagues import sportybet


def test_over15_aliases_accepted():
    for alias in ("1.5", "O1.5", "Over 1.5", "over_1_5"):
        assert M.parse_input(f"12345,{alias}", "over_1_5") == [("12345", "over_1_5")]


def test_import_rejects_bad_code_without_network():
    with pytest.raises(ValueError, match="valid SportyBet"):
        M.import_share_code("../bad", "2_odds")


def test_import_rejects_unknown_share_code():
    with patch("leagues.booking._read_share", return_value={"bizCode": 10001}):
        with pytest.raises(ValueError, match="recognize"):
            M.import_share_code("ABC123", "2_odds")


def test_import_rejects_unmapped_selection():
    board = {"fixtures": {"123": {"event_id": "123"}}}
    with patch("leagues.booking._read_share", return_value={
        "bizCode": 10000,
        "data": {"ticket": {"selections": [{
            "eventId": "123", "marketId": "nonexistent",
            "specifier": "", "outcomeId": "none"
        }]}}
    }), patch.object(sportybet, "_board_entries", return_value=[("x", {"event_id": "123"})]):
        with pytest.raises(ValueError, match="cannot be mapped"):
            M.import_share_code("ABC123", "2_odds", board=board)


def test_import_reports_exact_unsupported_selection():
    board = {"match": {"event_id": "sr:match:74165904"}}
    payload = {"bizCode": 10000, "data": {"ticket": {"selections": [{
        "eventId": "sr:match:74165904", "marketId": "999",
        "specifier": "", "outcomeId": "999"
    }]}}}
    with patch("leagues.booking._read_share", return_value=payload), patch.object(
        sportybet, "_board_entries", return_value=[("match", board["match"])]
    ):
        with pytest.raises(ValueError, match="marketId=999"):
            M.import_share_code("s8uamw", "2_odds", board=board)
