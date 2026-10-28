"""Opt-in once-per-run VPS PostgreSQL dump and verified encrypted S3 upload.

Requires DATABASE_URL, AWS_S3_BACKUP_BUCKET, AWS_S3_BACKUP_PREFIX, and
valid AWS CLI credentials. Intended for a systemd timer on an already
provisioned/hardened VPS, never run by GitHub Actions with real secrets.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from scripts.vps.backup_postgres import run_backup
from utils.vps_offsite import upload_verified_backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.output_dir.is_absolute():
            raise ValueError("backup directory must be absolute")
        url = os.environ["DATABASE_URL"]
        bucket = os.environ["AWS_S3_BACKUP_BUCKET"]
        prefix = os.environ["AWS_S3_BACKUP_PREFIX"]
        # Validate destination before creating any local backup.
        from utils.vps_offsite import s3_destination
        s3_destination(bucket, prefix, os.getenv("AWS_S3_ENDPOINT_URL"))
        manifest = run_backup(url, args.output_dir)
        archive = args.output_dir / manifest["archive_name"]
        report = upload_verified_backup(
            archive, archive.with_suffix(".json"),
            bucket=bucket, prefix=prefix,
            endpoint=os.getenv("AWS_S3_ENDPOINT_URL"),
        )
        print(json.dumps({"backup": manifest["archive_name"],
                          "offsite": report["status"],
                          "objects": report["objects"]}, sort_keys=True))
        return 0
    except Exception as exc:
        # Never print exception arguments; they might embed credentials.
        print(f"BACKUP_UPLOAD_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
