"""Private, verified S3-compatible backup transfer with no delete operations.

Requires AWS CLI v2 and a provider supporting SSE-S3 (AES256) metadata.
External destination configuration is operator-supplied; never preconfigured
to the public repository or active before an approved backup destination.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from utils.vps_restore import validate_archive

_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PREFIX_RE = re.compile(r"^[a-zA-Z0-9_/-]{1,120}$")


def s3_destination(bucket: str, prefix: str, endpoint: str | None = None):
    if not _BUCKET_RE.fullmatch(bucket) or ".." in bucket:
        raise ValueError("invalid S3 bucket name")
    prefix = prefix.strip("/")
    if not _PREFIX_RE.fullmatch(prefix) or "//" in prefix or ".." in prefix:
        raise ValueError("invalid S3 key prefix")
    if endpoint:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment
        ):
            raise ValueError("S3 endpoint requires HTTPS with no URL credentials")
    return bucket, prefix, endpoint


def _digest(file: Path):
    h = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_verified_backup(archive: Path, manifest: Path, *,
                           bucket: str, prefix: str, endpoint=None, runner=None):
    bucket, prefix, endpoint = s3_destination(bucket, prefix, endpoint)
    # No external side effects until manifest and source file integrity pass.
    if manifest.with_suffix(".dump") != archive:
        raise ValueError("archive and manifest must have matching names")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not data.get("source_database"):
        raise ValueError("missing source database in manifest")
    if not isinstance(data["source_database"], str):
        raise ValueError("invalid source database in manifest")
    # This verifies the checksum as well as the manifest/filename, but the
    # target is intentionally synthetic and distinct from the source.
    validate_archive(archive, manifest, "betsightly_restore_s3validator")
    run = runner or subprocess.run
    base = ["aws", "--no-cli-pager"]
    if endpoint:
        base.extend(["--endpoint-url", endpoint])

    outputs = []
    for file, digest in ((archive, data["sha256"]), (manifest, _digest(manifest))):
        key = f"{prefix}/{file.name}"
        remote = f"s3://{bucket}/{key}"
        run(base + ["s3", "cp", str(file), remote,
                    "--sse", "AES256",
                    "--metadata", f"sha256={digest}",
                    "--only-show-errors", "--no-progress"],
            check=True, capture_output=True, timeout=1200)
        check = run(base + [
            "s3api", "head-object", "--bucket", bucket, "--key", key,
            "--output", "json",
        ], check=True, capture_output=True, timeout=60)
        info = json.loads(check.stdout)
        if (
            info.get("ContentLength") != file.stat().st_size
            or (info.get("Metadata") or {}).get("sha256") != digest
            or info.get("ServerSideEncryption") != "AES256"
        ):
            raise RuntimeError("remote backup verification failed")
        outputs.append({"object_key": key, "size_bytes": file.stat().st_size,
                        "verified_sha256_metadata": True, "encrypted": True})
    return {"status": "offsite_objects_verified", "bucket": bucket,
            "objects": outputs, "note": "A real restore test is still required"}
