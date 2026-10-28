import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.vps_offsite import s3_destination, upload_verified_backup


@pytest.mark.parametrize("bucket,prefix,endpoint", [
    ("ab", "backups", None),
    ("mybucket", "../prod", None),
    ("mybucket", "ok", "http://insecure.example"),
    ("mybucket", "ok", "https://user:pw@storage.example"),
    ("mybucket", "ok", "https://storage.example/secret"),
    ("mybucket", "ok//broken", None),
])
def test_rejects_unsafe_s3_destinations(bucket, prefix, endpoint):
    with pytest.raises(ValueError):
        s3_destination(bucket, prefix, endpoint)


def test_accepts_valid_backup_destination():
    assert s3_destination("betsightly-backups", "football/prod",
                          "https://s3.example.com") == (
                              "betsightly-backups", "football/prod",
                              "https://s3.example.com")


def _fixture(tmp_path: Path):
    archive = tmp_path / "betsightly-fixture.dump"
    archive.write_bytes(b"synthetic backup payload")
    manifest = archive.with_suffix(".json")
    manifest.write_text(json.dumps({
        "source_database": "betsightly_ci_source",
        "archive_name": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "status": "archive_verified_not_restore_tested",
    }))
    return archive, manifest


def test_upload_checks_both_s3_objects_and_encryption(tmp_path):
    archive, manifest = _fixture(tmp_path)
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if "head-object" in args:
            key = args[args.index("--key")+1]
            file = archive if key.endswith(".dump") else manifest
            return SimpleNamespace(stdout=json.dumps({
                "ContentLength": file.stat().st_size,
                "Metadata": {"sha256": hashlib.sha256(file.read_bytes()).hexdigest()},
                "ServerSideEncryption": "AES256",
            }).encode())
        return SimpleNamespace(stdout=b"")

    out = upload_verified_backup(
        archive, manifest, bucket="betsightly-backups",
        prefix="football", runner=fake_run
    )
    assert out["status"] == "offsite_objects_verified"
    assert len(out["objects"]) == 2
    assert len([c for c in commands if "head-object" in c]) == 2
    assert all("--sse" in c for c in commands if "cp" in c)


def test_upload_rejects_remote_missing_encryption(tmp_path):
    archive, manifest = _fixture(tmp_path)

    def fake_run(args, **kwargs):
        if "head-object" in args:
            return SimpleNamespace(stdout=json.dumps({
                "ContentLength": archive.stat().st_size,
                "Metadata": {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
                "ServerSideEncryption": None,
            }).encode())
        return SimpleNamespace(stdout=b"")

    with pytest.raises(RuntimeError, match="verification failed"):
        upload_verified_backup(archive, manifest,
                               bucket="betsightly-backups",
                               prefix="football", runner=fake_run)


def test_corrupted_archive_is_rejected_before_network(tmp_path):
    archive, manifest = _fixture(tmp_path)
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        upload_verified_backup(archive, manifest,
                               bucket="betsightly-backups", prefix="football",
                               runner=lambda *a, **k: pytest.fail("network called"))
