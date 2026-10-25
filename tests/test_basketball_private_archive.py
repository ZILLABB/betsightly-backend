"""End-to-end signed NBA export -> isolated SQL store -> verified admin view."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_coldstart import _json, _signed
from basketball.research_data import write_games
from basketball.research_opening_score import capture as score_capture
from basketball.research_early_advanced_ops import (
    capture as advanced_capture, settle as advanced_settle,
)
from basketball.research_opening_score import settle as score_settle
from basketball.research_private_bundle import (
    VERSION, export_bundle, inspect_bundle, unchanged_prior,
)
from basketball.research_private_store import import_bundle, latest_bundle
from basketball.research_private_bundle import report_from_bundle
from tests.test_basketball_early_advanced_ops import setup as setup_lab

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
DONE = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)


def recorded(tmp_path):
    games = setup_lab(tmp_path)
    assert score_capture(tmp_path, now=NOW)["created"] == 1
    assert advanced_capture(tmp_path, now=NOW)["created"] == 1
    result = export_bundle(tmp_path)
    assert result["version"] == VERSION
    assert len(result["fixtures"]) == 1
    assert len(result["records"]["opening_score"]) == 1
    assert len(result["records"]["early_advanced"]) == 1
    assert not result["records"]["moneyline"]
    assert inspect_bundle(result)["summary"]["fixtures"] == 1
    return games, result


def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    return sessionmaker(bind=engine)()


def test_private_local_export_only_copies_recorded_game(tmp_path):
    _, bundle = recorded(tmp_path)
    assert bundle["research_only"] is True
    assert len(_json(bundle).encode()) < 750000
    assert bundle["fixtures"][0]["game_id"] == "29000"
    assert bundle["records"]["early_advanced"][0]["sha256"]


def test_hosted_snapshot_is_immutable_and_retry_idempotent(tmp_path):
    _, bundle = recorded(tmp_path)
    with session() as db:
        first = import_bundle(bundle, db=db)
        assert first["status"] == "saved_and_verified"
        assert first["fixture_count"] == 1
        assert import_bundle(bundle, db=db)["status"] == "already_saved"
        saved = latest_bundle(db)
        assert saved == bundle
        assert report_from_bundle(saved)["summary"]["fixtures"] == 1


def test_replacing_forecast_even_if_rehashed_must_be_rejected(tmp_path):
    _, bundle = recorded(tmp_path)
    with session() as db:
        import_bundle(bundle, db=db)
        forged = deepcopy(bundle)
        row = forged["records"]["opening_score"][0]
        row["predicted_total"] += 4
        row["predicted_home_points"] += 2
        row["predicted_away_points"] += 2
        row["sha256"] = _signed({k:v for k,v in row.items() if k!="sha256"})
        # Remains internally arithmetic-consistent, but downstream advanced
        # signed reference still points to the ORIGINAL forecast.
        with pytest.raises(ValueError):
            import_bundle(forged, db=db)
        assert latest_bundle(db) == bundle


def test_missing_saved_forecast_is_never_treated_as_new_archive(tmp_path):
    _, bundle = recorded(tmp_path)
    with session() as db:
        import_bundle(bundle, db=db)
        changed = deepcopy(bundle)
        changed["records"]["early_advanced"] = []
        # Must reject even though earlier original-score record remains.
        with pytest.raises(ValueError, match="overwrite or delete"):
            import_bundle(changed, db=db)


def test_verified_final_can_append_without_rewriting_forecast(tmp_path):
    games, old = recorded(tmp_path)
    with session() as db:
        assert import_bundle(old, db=db)["status"] == "saved_and_verified"
        games[-1] = {**games[-1], "status": "final",
                     "home_score": 114, "away_score": 102}
        write_games(games, tmp_path / "nba_games.jsonl")
        assert score_settle(tmp_path, now=DONE)["new_settlements"] == 1
        assert advanced_settle(tmp_path, now=DONE)["new_settlements"] == 1
        latest = export_bundle(tmp_path)
        assert len(latest["records"]["opening_score_finals"]) == 1
        assert len(latest["records"]["early_advanced_finals"]) == 1
        saved = import_bundle(latest, db=db)
        assert saved["status"] == "saved_and_verified"
        assert latest_bundle(db) == latest
        assert report_from_bundle(latest)["games"][0]["status"] == "verified_settled"
        assert latest["records"]["opening_score"] == old["records"]["opening_score"]


def test_signed_ledger_integrity_blocks_before_any_database_change(tmp_path):
    _, bundle = recorded(tmp_path)
    row = bundle["records"]["early_advanced"][0]
    row["predicted_total"] += 3
    with session() as db:
        with pytest.raises(ValueError):
            import_bundle(bundle, db=db)
        assert latest_bundle(db) is None


def test_game_identity_changed_blocks_reimport(tmp_path):
    _, bundle = recorded(tmp_path)
    with session() as db:
        import_bundle(bundle, db=db)
        changed = deepcopy(bundle)
        changed["fixtures"][0]["home_id"] = "99"
        with pytest.raises(ValueError):
            import_bundle(changed, db=db)
        assert latest_bundle(db) == bundle
