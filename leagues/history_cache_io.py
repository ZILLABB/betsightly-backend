"""Small, local, crash-safe helpers for completed history artifacts.

The lock coordinates processes sharing one filesystem. It does not coordinate
different Render instances; the history repair must not be deployed until a
shared cache/lease is configured or a single prewarm owner is established.
"""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


def read_complete(path: Path, schema: int, *, required: str) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(data, dict) and data.get("_cache_schema") == schema
                and not data.get("_failed_leagues")
                and not data.get("failed_leagues")
                and required in data):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def replace_complete(path: Path, data: dict, schema: int, *, required: str) -> None:
    if (not isinstance(data, dict) or data.get("_cache_schema") != schema
            or data.get("_failed_leagues") or data.get("failed_leagues")
            or required not in data):
        raise ValueError("refusing incomplete history cache")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def local_refresh_claim(path: Path, *, stale_after: float = 600):
    """Nonblocking same-filesystem process lease; caller serves stale if busy."""
    lock = path.with_name(path.name + ".refresh.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    try:
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > stale_after:
                        lock.unlink()
                        continue
                except OSError:
                    pass
                break
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                acquired = True
                break
        yield acquired
    finally:
        if acquired:
            lock.unlink(missing_ok=True)
