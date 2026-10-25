"""Persistence, duplicate claims, authenticated history data and safe NBA settlement."""
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from growth import basketball_history as bh
from growth import basketball_settlement as bs


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    import database
    engine = create_engine("sqlite:///" + str(tmp_path / "nba_history.sqlite"))
    monkeypatch.setattr(database, "engine", engine)
    return engine


def _picks():
    return [{"eventId": "sr:match:100", "marketId": "219",
             "outcomeId": "4", "specifier": ""}]


def _legs(*, when=None):
    now = datetime.now(timezone.utc)
    return [{
        "event_id": "sr:match:100", "market_id": "219", "outcome_id": "4",
        "specifier": "", "home_team": "New York Knicks",
        "away_team": "Orlando Magic", "competition": "NBA",
        "selection": "New York Knicks", "odds": 1.65,
        "kickoff_ms": int((when or (now - timedelta(hours=4))).timestamp() * 1000),
    }]


def test_ledger_claim_is_unique_and_status_persists(history_db):
    one, first = bh.claim(_picks(), _legs(), 2.0, "snapshot-1")
    two, second = bh.claim(_picks(), _legs(), 2.0, "snapshot-1")
    assert one is True
    assert two is False
    assert first["fingerprint"] == second["fingerprint"]
    assert first["status"] == "creating"
    bh.mark(first["fingerprint"], status="verifying", share_code="HIDE123")
    assert bh.list_recent()["tickets"][0]["share_code"] is None
    exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    bh.mark(first["fingerprint"], status="active",
            verified_odds=2.4, odds_source="sportybet_code_readback",
            expires_at=exp)
    saved = bh.list_recent()["tickets"][0]
    assert saved["share_code"] == "HIDE123"
    assert saved["verified_odds"] == 2.4
    assert saved["legs"][0]["result"] == "pending"
    assert saved["detail"]["ticket_status"] == "pending"


def test_ledger_prevents_selection_changes_after_settlement(history_db):
    _, claimed = bh.claim(_picks(), _legs(), 2.0, "snapshot")
    fp = claimed["fingerprint"]
    bh.mark(fp, status="active")
    updated = bh.get(fp)["legs"]
    updated[0] = {**updated[0], "result": "won",
                  "score": {"home": 109, "away": 95},
                  "score_source": "ESPN_NBA_FINAL"}
    bh.update_results(fp, updated, datetime.now(timezone.utc).isoformat(), "won")
    assert bh.get(fp)["status"] == "won"
    updated[0]["result"] = "lost"
    with pytest.raises(ValueError, match="cannot be silently overwritten"):
        bh.update_results(fp, updated, datetime.now(timezone.utc).isoformat(), "lost")


def _espn_event(when, home="New York Knicks", away="Orlando Magic", *,
                score_home="109", score_away="95", final=True):
    return {"id": "401000000", "date": when.isoformat(),
            "status": {"type": {"completed": final, "state": "post" if final else "in"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": home}, "score": score_home},
                {"homeAway": "away", "team": {"displayName": away}, "score": score_away},
            ]}]}


def test_nba_result_requires_exact_teams_time_and_final():
    tipoff = datetime.now(timezone.utc) - timedelta(hours=4)
    leg = _legs(when=tipoff)[0]
    event = bs._event_record(_espn_event(tipoff))
    assert bs._match(leg, [event]) is event
    assert bs.settle_leg(leg, event)["result"] == "won"
    assert bs._event_record(_espn_event(tipoff, final=False)) is None
    assert bs._match(leg, [bs._event_record(
        _espn_event(tipoff, home="Los Angeles Lakers"))]) is None
    altered = dict(event, tipoff=tipoff + timedelta(hours=8))
    assert bs._match(leg, [altered]) is None


def test_nba_total_points_and_european_fixture_policy():
    tipoff = datetime.now(timezone.utc) - timedelta(hours=4)
    event = bs._event_record(_espn_event(tipoff, score_home="112", score_away="110"))
    total = dict(_legs(when=tipoff)[0], market_id="225", outcome_id="12",
                 specifier="total=220.5")
    assert bs.settle_leg(total, event)["result"] == "won"
    total["outcome_id"] = "13"
    assert bs.settle_leg(total, event)["result"] == "lost"
    total["specifier"] = "total=222"
    assert bs.settle_leg(total, event)["result"] == "void"
    total["competition"] = "Liga ACB"
    assert bs._match(total, [event]) is None


def test_reconcile_uses_final_source_without_betting(history_db, monkeypatch):
    _, claimed = bh.claim(_picks(), _legs(), 2.0, "snapshot")
    bh.mark(claimed["fingerprint"], status="active")
    tipoff = datetime.fromtimestamp(_legs()[0]["kickoff_ms"] / 1000,
                                     timezone.utc)
    event = bs._event_record(_espn_event(tipoff))
    monkeypatch.setattr(bs, "_fetch_day", lambda day, get=None: [event])
    result = bs.settle_due()
    assert result["status"] == "success"
    assert result["nba_final_legs"] == 1
    saved = bh.list_recent()["tickets"][0]
    assert saved["status"] == "won"
    assert saved["legs"][0]["score_source"] == "ESPN_NBA_FINAL"
    assert saved["legs"][0]["score"] == {"home": 109, "away": 95}
    again = bs.settle_due(force=True)
    assert again["nba_final_legs"] == 0
