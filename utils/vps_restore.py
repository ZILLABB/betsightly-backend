"""Pure safety guards for a disposable, isolated PostgreSQL restore drill."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


RESTORE_NAME = re.compile(r"^betsightly_restore_[a-z0-9_]{8,40}$")


def validate_restore_name(target: str, source: str) -> None:
    if target == source or not RESTORE_NAME.fullmatch(target):
        raise ValueError("restore target must be a distinct disposable betsightly_restore_ database")


def validate_archive(archive: Path, manifest: Path, target: str):
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("backup archive must be an ordinary file")
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError("manifest must be an ordinary file")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    source = data.get("source_database")
    if not isinstance(source, str):
        raise ValueError("manifest has no source_database")
    validate_restore_name(target, source)
    if data.get("archive_name") != archive.name:
        raise ValueError("manifest archive name mismatch")
    if data.get("status") != "archive_verified_not_restore_tested":
        raise ValueError("manifest status is not a verified archive")
    digest = hashlib.sha256()
    with archive.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    if (
        digest.hexdigest() != data.get("sha256")
        or archive.stat().st_size != data.get("size_bytes")
    ):
        raise ValueError("archive SHA-256 or size does not match manifest")
    return data
