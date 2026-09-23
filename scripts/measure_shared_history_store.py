"""Measure completed-artifact reads in an explicitly disposable local database.

This script writes only the two test artifact keys to a local PostgreSQL URL.
Never point it at production or staging.
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, event

from leagues import shared_history_store as store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432:
        parser.error("only the disposable local PostgreSQL port 55432 is allowed")
    board = json.loads(args.snapshot.read_text(encoding="utf-8"))
    history = board["historical_inputs"]
    engine = create_engine(args.url)
    queries = 0

    def count(*_args):
        nonlocal queries
        queries += 1

    event.listen(engine, "before_cursor_execute", count)
    for key, source, required in (
            ("perf_base_rates", history["base_rates"], "_priors"),
            ("perf_team_history", history["team_history"], "matches")):
        schema = int(source["_cache_schema"])
        with store.claim(key, schema, engine=engine) as owner:
            if not owner:
                raise RuntimeError("disposable performance key is leased")
            if not store.promote(key, schema, source, owner,
                                 required=required, engine=engine):
                raise RuntimeError("test artifact promotion failed")
        samples = []
        start_queries = queries
        for _ in range(20):
            start = time.perf_counter()
            assert store.read(key, schema, required=required, engine=engine)
            samples.append((time.perf_counter() - start) * 1000)
        print(json.dumps({
            "artifact": key,
            "payload_bytes": len(json.dumps(source, ensure_ascii=False).encode()),
            "median_read_ms": round(statistics.median(samples), 3),
            "max_read_ms": round(max(samples), 3),
            "queries_per_read": (queries - start_queries) / len(samples),
        }))
    engine.dispose()


if __name__ == "__main__":
    main()
