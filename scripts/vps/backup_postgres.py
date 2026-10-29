"""Create and verify a permission-restricted PostgreSQL custom-format dump.

This is a *local backup primitive*, not off-site backup or restore proof.
Use a compatible pg_dump (PostgreSQL 18+ for the live football database).
Never put database URLs/passwords on process command lines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

from utils.vps_backup import pg_environment


def run_backup(database_url: str, output_dir: Path):
    env, db_name = pg_environment(database_url)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir / f"betsightly-{stamp}-{uuid4().hex[:8]}.dump"
    metadata = destination.with_suffix(".json")
    # Exclusive private creation prevents clobbering a prior backup.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
             "--file", str(destination)],
            check=True, capture_output=True, timeout=900, env=env,
        )
        listing = subprocess.run(
            ["pg_restore", "--list", str(destination)],
            check=True, capture_output=True, timeout=60, env=env,
        ).stdout.decode("utf-8", errors="replace")
        if " TABLE " not in listing and " TABLE DATA " not in listing:
            raise RuntimeError("backup has no verified table entries")
        hasher = hashlib.sha256()
        with destination.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                hasher.update(chunk)
        result = {
            "source_database": db_name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "size_bytes": destination.stat().st_size,
            "sha256": hasher.hexdigest(),
            "archive_name": destination.name,
            "status": "archive_verified_not_restore_tested",
        }
        fd = os.open(metadata, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(result, out, sort_keys=True, indent=2)
            out.write("\n")
        return result
    except Exception:
        destination.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.output_dir.is_absolute():
            raise ValueError("backup directory must be an absolute path")
        result = run_backup(os.environ["DATABASE_URL"], args.output_dir)
    except Exception as exc:
        print(f"BACKUP_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
