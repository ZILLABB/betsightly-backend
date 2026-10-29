import hashlib
import json

import pytest

from utils.vps_restore import validate_archive, validate_restore_name


@pytest.mark.parametrize("bad", [
    "betsightly", "betsightly_lik1", "postgres", "betsightly_restore_",
    "betsightly_restore_abc", "betsightly_restore_PROD123456",
    "betsightly_restore_../../prod",
])
def test_restore_rejects_untrusted_target_name(bad):
    with pytest.raises(ValueError):
        validate_restore_name(bad, "betsightly_lik1")


def test_restore_rejects_identical_source_and_destination():
    with pytest.raises(ValueError):
        validate_restore_name("betsightly_restore_fixture12",
                              "betsightly_restore_fixture12")


def test_manifest_verified_before_any_database_connection(tmp_path):
    backup = tmp_path / "betsightly-20261028.dump"
    backup.write_bytes(b"fake archive bytes only for testing checksum")
    manifest = tmp_path / "betsightly-20261028.json"
    payload = {
        "source_database": "betsightly_lik1",
        "archive_name": backup.name,
        "size_bytes": backup.stat().st_size,
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "status": "archive_verified_not_restore_tested",
    }
    manifest.write_text(json.dumps(payload))
    assert validate_archive(
        backup, manifest, "betsightly_restore_fixture12"
    )["source_database"] == "betsightly_lik1"
    backup.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        validate_archive(backup, manifest, "betsightly_restore_fixture12")


def test_restore_rejects_manifest_for_other_file(tmp_path):
    backup = tmp_path / "safe.dump"
    backup.write_bytes(b"fixture")
    manifest = tmp_path / "safe.json"
    manifest.write_text(json.dumps({
        "source_database": "betsightly_lik1",
        "archive_name": "different.dump",
        "size_bytes": 7,
        "sha256": hashlib.sha256(b"fixture").hexdigest(),
        "status": "archive_verified_not_restore_tested",
    }))
    with pytest.raises(ValueError):
        validate_archive(backup, manifest, "betsightly_restore_fixture12")
