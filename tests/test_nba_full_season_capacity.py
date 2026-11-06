"""A complete NBA season must fit the private research/archive/backup bounds."""
import pytest

from basketball import research_private_bundle as bundle
from basketball import research_ops_health as ops
from basketball import research_full_recovery as full
from basketball import research_safe_migrate as migrate


def test_regular_season_plus_playoffs_fit_private_archive_cohort():
    # NBA has 30 teams, 82 regular games each; each game has two teams.
    assert 30 * 82 // 2 == 1230
    assert bundle.MAX_FIXTURES >= 1230 + 100
    assert bundle.MAX_BYTES >= 8_000_000
    assert ops.MAX_HISTORY >= 900
    assert ops.MAX_BACKUP_BYTES < full.MAX_RECOVERY_BYTES
    assert full.MAX_RECOVERY_BYTES == migrate.MAX_BACKUP_FILE


def test_forecast_ledger_admits_full_season_but_rejects_unbounded_payloads():
    sample = [{"game_id": str(i)} for i in range(1300)]
    ids = bundle._validated_records(sample, kind="moneyline")
    assert len(ids) == 1300
    with pytest.raises(ValueError, match="count invalid"):
        bundle._validated_records(
            [{"game_id": str(i)} for i in range(bundle.MAX_FIXTURES + 1)],
            kind="moneyline",
        )
    with pytest.raises(ValueError, match="duplicate"):
        bundle._validated_records(
            [{"game_id": "100"}, {"game_id": "100"}], kind="moneyline"
        )


def test_private_blob_worker_bounds_track_verifiable_python_export(tmp_path):
    source = (
        tmp_path.parent / "ops" / "nba_vercel_scheduler" / "api" / "backup-v2.js"
    )
    # Avoid filesystem assumptions when test is invoked from a different cwd.
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "ops/nba_vercel_scheduler/api/backup-v2.js"
    code = source.read_text(encoding="utf-8")
    assert f"raw.byteLength > {full.MAX_RECOVERY_BYTES:_}" in code
    assert "access:'private'" in code
    assert "hash(reread) !== hash(raw)" in code
    assert "verified_full_private_blob_readback" in code
