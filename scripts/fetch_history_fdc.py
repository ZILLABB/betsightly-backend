"""Compatibility entry point for the provenance-first FDC fetcher.

The old script used to overwrite data/api-football/matches.csv directly and
mixed price timing semantics. The v2 implementation writes a provenance-rich
raw warehouse file by default and requires --legacy-output for any overwrite.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_history_fdc_v2 import *  # noqa: F401,F403,E402
from scripts.fetch_history_fdc_v2 import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
