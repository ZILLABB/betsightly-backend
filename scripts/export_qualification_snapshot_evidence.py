"""Read-only export of original decision snapshots for qualification shadow audits.

Run only when the football Postgres is accessible. No DDL or UPDATE/INSERT.
Never invent snapshot captured times from published dates.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from database import engine
from leagues.decision_archive import board_snapshots


def export(*, days: int = 45, maximum: int = 500) -> list[dict]:
    if not 1 <= days <= 365 or not 1 <= maximum <= 5000:
        raise ValueError("unsupported export bounds")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = (select(board_snapshots.c.snapshot_id,
                    board_snapshots.c.generated_at,
                    board_snapshots.c.payload_sha256,
                    board_snapshots.c.payload)
             .where(board_snapshots.c.generated_at >= cutoff)
             .order_by(board_snapshots.c.generated_at.asc())
             .limit(maximum))
    result = []
    # This query does not create tables, request new predictions or settle legs.
    with engine.connect() as connection:
        for row in connection.execute(query).mappings():
            raw = gzip.decompress(row["payload"])
            if hashlib.sha256(raw).hexdigest() != row["payload_sha256"]:
                raise ValueError("immutable snapshot checksum mismatch")
            payload = json.loads(raw.decode("utf-8"))
            candidates = payload.get("candidates") or []
            # The original archive has no competition_type field. The known
            # domestic-cup registry is an annotation, not a fixture relink.
            from leagues.competition_registry import competition_for
            for candidate in candidates:
                slug = candidate.get("league_slug")
                meta = competition_for(slug) if slug else None
                candidate["competition_type"] = (
                    meta.competition_type if meta else "UNKNOWN")
            captured = row["generated_at"]
            if captured.tzinfo is None:
                raise ValueError("snapshot timestamp must be timezone-aware")
            result.append({
                "snapshot_id": row["snapshot_id"],
                "generated_at": captured.astimezone(timezone.utc).isoformat(),
                "candidates": candidates,
            })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--maximum", type=int, default=500)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = export(days=args.days, maximum=args.maximum)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot_count": len(rows), "output": str(path),
                      "mode": "READ_ONLY"}))


if __name__ == "__main__":
    main()
