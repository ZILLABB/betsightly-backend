"""Rollover must never chase losses or pre-publish future stages."""
import pytest

from leagues.rollover_lifecycle import chain_state
from leagues import daily_feed


def _day(day_number, day, status="pending"):
    return {"day_number": day_number, "date": day, "status": status,
            "picks": [{"match_id": str(day_number), "status": status}],
            "combined_odds": 2.0, "hit_probability": .5}


def test_day_two_is_blocked_while_day_one_is_unsettled():
    result = chain_state([_day(1, "2026-10-09")], "2026-10-10")
    assert result["status"] == "awaiting_settlement"
    assert not result["can_generate"]


def test_day_two_is_allowed_only_after_day_one_won():
    result = chain_state([_day(1, "2026-10-09", "won")], "2026-10-10")
    assert result["status"] == "ready"
    assert result["day_number"] == 2
    assert result["can_generate"]


def test_day_three_waits_for_both_prior_wins():
    days = [_day(1, "2026-10-09", "won"),
            _day(2, "2026-10-10", "won")]
    result = chain_state(days, "2026-10-11")
    assert result["status"] == "ready"
    assert result["day_number"] == 3


@pytest.mark.parametrize("current", ["2026-10-10", "2026-10-11"])
def test_legacy_precommitted_future_day_is_not_active_after_loss(current):
    days = [_day(1, "2026-10-09", "lost"),
            _day(2, "2026-10-10", "pending"),
            _day(3, "2026-10-11", "pending")]
    decision = chain_state(days, current)
    assert decision["status"] == "failed"
    assert decision["active_date"] is None
    assert not decision["can_generate"]


def test_restart_never_conflicts_with_old_precommitted_dates():
    days = [_day(1, "2026-10-09", "lost"),
            _day(2, "2026-10-10", "lost"),
            _day(3, "2026-10-11", "pending")]
    decision = chain_state(days, "2026-10-12")
    assert decision["status"] == "failed"
    assert decision["new_chain"]
    assert decision["day_number"] == 1


def test_successful_three_days_resets_next_day_only():
    days = [_day(1, "2026-10-09", "won"),
            _day(2, "2026-10-10", "won"),
            _day(3, "2026-10-11", "won")]
    assert chain_state(days, "2026-10-11")["status"] == "completed"
    assert chain_state(days, "2026-10-12")["new_chain"]


def test_void_is_not_mistaken_for_confirmed_win():
    assert chain_state([_day(1, "2026-10-09", "void")],
                       "2026-10-10")["status"] == "voided"


def test_precommitted_day_can_be_honoured_if_previous_days_won():
    days = [_day(1, "2026-10-09", "won"),
            _day(2, "2026-10-10", "pending")]
    assert chain_state(days, "2026-10-10")["status"] == "active"


def test_public_chain_stops_after_previous_loss_but_preserves_history(monkeypatch):
    original = [_day(1, "2026-10-09", "lost"),
                _day(2, "2026-10-10", "lost"),
                _day(3, "2026-10-11", "pending")]
    monkeypatch.setattr("leagues.rollover_db.load_chain",
                        lambda _day: {"start_date": "2026-10-08",
                                      "days": original, "status": "active"})
    monkeypatch.setattr("leagues.rollover_db.append_day",
                        lambda *_: (_ for _ in ()).throw(
                            AssertionError("failed chain must not add picks")))
    monkeypatch.setattr("leagues.rollover_db.reset_chain",
                        lambda *_: (_ for _ in ()).throw(
                            AssertionError("must preserve historical results")))
    result = daily_feed._build_rollover([], "2026-10-11")
    assert result["selected"] is False
    assert result["games"] == []
    assert result["challenge_status"] == "failed"
    assert result["chain_length"] == 3
    assert result["chain"][0]["status"] == "lost"
    assert "stopped" in result["reason"]


def test_no_future_day_is_generated_in_preview(monkeypatch):
    # The only available fixture is on Oct 12. The Oct 11 daily challenge
    # must not prebook that future date, even with zero current-day matches.
    later = {"match_id": "future", "safe_tier_eligible": True,
             "_fixture": {"commence_time": "2026-10-12T15:00:00Z"}}
    monkeypatch.setattr("leagues.selection.select_rollover_day",
                        lambda picks, **kw: (_ for _ in ()).throw(
                            AssertionError("must not select future fixtures")))
    result = daily_feed._build_rollover([later], "2026-10-11", preview=True)
    assert result["chain"] == []
    assert result["selected"] is False


def test_previous_pending_day_blocks_new_bet(monkeypatch):
    original = [_day(1, "2026-10-10", "pending")]
    monkeypatch.setattr("leagues.rollover_db.load_chain",
                        lambda _: {"start_date": "2026-10-10",
                                   "days": original, "status": "active"})
    result = daily_feed._build_rollover([], "2026-10-11")
    assert not result["selected"]
    assert result["challenge_status"] == "awaiting_settlement"


def test_old_chain_cleanup_is_disabled_for_audit_integrity(monkeypatch):
    from leagues import rollover_db
    assert rollover_db.cleanup_old_chains(keep_recent_chains=1) == 0
