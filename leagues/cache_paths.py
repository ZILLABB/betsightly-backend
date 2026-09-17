"""Configurable runtime cache locations; production defaults stay unchanged."""
from __future__ import annotations

import os
from pathlib import Path


def cache_path(default: Path) -> Path:
    root = os.getenv("BETSIGHTLY_CACHE_ROOT", "").strip()
    if not root:
        return default
    return Path(root) / default.name
